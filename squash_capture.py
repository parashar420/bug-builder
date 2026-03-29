from mitmproxy import http, ctx
import json
import os
from datetime import datetime

class SquashCapture:
    def __init__(self):
        self.save_dir = "captured_squash_data"
        os.makedirs(self.save_dir, exist_ok=True)
        ctx.log.info(f"📁 Saving Squash TM data to: {self.save_dir}/")
    
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
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"execution_{execution_id}_{timestamp}.json"
            filepath = os.path.join(self.save_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(flow.response.text)
            
            ctx.log.info(f"✅ Saved: {filename}")
            
        except Exception as e:
            ctx.log.error(f"❌ Error: {e}")
    
    def extract_execution_id(self, url: str) -> str:
        try:
            if '?' in url:
                return url.split('/')[-1].split('?')[0]
            return "unknown"
        except:
            return "unknown"

addons = [SquashCapture()]
