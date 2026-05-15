from mitmproxy import http, ctx
import json
import os
from datetime import datetime
import yaml

class SquashCapture:
    def __init__(self):
        self.capture_dir, self.testcase_dir = self._load_capture_paths()
        self.mode_state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".capture_mode")
        os.makedirs(self.capture_dir, exist_ok=True)
        os.makedirs(self.testcase_dir, exist_ok=True)
        ctx.log.info(f"📁 Saving Squash TM data to: {self.capture_dir}/")
        ctx.log.info(f"📁 Saving testcase captures to: {self.testcase_dir}/")
        self._ensure_mode_state_file()

    def _load_capture_paths(self):
        """Load capture directories from config.yaml with safe fallbacks."""
        default_capture_dir = "captured_squash_data"
        default_testcase_dir = "captured_testcase_data"

        try:
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as config_file:
                    config = yaml.safe_load(config_file) or {}
                paths = config.get("paths", {})
                capture_dir = paths.get("capture_dir", default_capture_dir)
                testcase_dir = paths.get("testcase_capture_dir", default_testcase_dir)
                return capture_dir, testcase_dir
        except Exception as exc:
            ctx.log.warn(f"⚠️ Failed to load config.yaml for capture paths: {exc}")

        return default_capture_dir, default_testcase_dir

    def write_payload(self, save_path: str, response_text: str) -> None:
        """Persist payload to disk, pretty-printing JSON when possible."""
        payload_text = response_text or ""
        directory = os.path.dirname(save_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        try:
            parsed = json.loads(payload_text)
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(parsed, f, indent=2, ensure_ascii=False)
        except Exception:
            # Fallback for non-JSON payloads or malformed responses
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(payload_text)

    def _ensure_mode_state_file(self) -> None:
        """Create mode state file if missing so capture has a deterministic default."""
        try:
            if not os.path.exists(self.mode_state_file):
                with open(self.mode_state_file, "w", encoding="utf-8") as f:
                    f.write("gherkin")
        except Exception as exc:
            ctx.log.warn(f"⚠️ Failed to initialize capture mode file: {exc}")

    def get_active_mode(self) -> str:
        """Read current UI-selected capture mode from shared state file."""
        try:
            with open(self.mode_state_file, "r", encoding="utf-8") as f:
                mode = (f.read() or "").strip().lower()
            if mode in {"gherkin", "testcases"}:
                return mode
        except Exception:
            pass
        return "gherkin"
    
    def response(self, flow: http.HTTPFlow) -> None:
        if self.is_squash_execution_api(flow.request):
            self.save_squash_response(flow)
    
    def is_squash_execution_api(self, request) -> bool:
        url = request.pretty_url
        
        if ("squash.internetbrands.com" in url and
            "frontEndErrorIsHandled=true" in url):
            ctx.log.info(f"🎯 Found Squash execution API: {url}")
            return True
        
        return False
    
    def save_squash_response(self, flow: http.HTTPFlow) -> None:
        try:
            execution_id = self.extract_execution_id(flow.request.pretty_url)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            payload_type = self.detect_payload_type(flow.request.pretty_url, flow.response.text)
            filename = f"{payload_type}_{execution_id}_{timestamp}.json"
            active_mode = self.get_active_mode()

            # Route by active UI toggle mode only.
            target_dir = self.testcase_dir if active_mode == "testcases" else self.capture_dir
            save_path = os.path.join(target_dir, filename)
            self.write_payload(save_path, flow.response.text)
            ctx.log.info(f"✅ Saved ({active_mode}/{payload_type}): {save_path}")
        except Exception as e:
            ctx.log.error(f"❌ Error saving Squash response: {e}")

    def detect_payload_type(self, url: str, response_text: str) -> str:
        """Classify captured response to help downstream filtering and routing."""
        lower_url = (url or "").lower()
        body = response_text or ""
        lower_body = body.lower()

        if (
            "/executions/" in lower_url
            or "/backend/execution/" in lower_url
            or "<executionview" in lower_body
            or '"executionStepViews"' in body
        ):
            return "execution"

        if (
            "/test-cases/" in lower_url
            or "/backend/test-case-view/" in lower_url
            or "<testcasedto" in lower_body
            or '"testSteps"' in body
        ):
            return "testcase"

        return "unknown"
    
    def extract_execution_id(self, url: str) -> str:
        try:
            if '?' in url:
                return url.split('/')[-1].split('?')[0]
            return "unknown"
        except:
            return "unknown"

addons = [SquashCapture()]
