# Browser Proxy Setup for Squash TM Capture

## Quick Start

### Option 1: Automatic Browser Launch

1. **Edit browser preference** in `browser_config.py`:
   ```python
   # Choose ONE browser:
   USE_CHROME = True     # For Chrome
   USE_FIREFOX = False   # For Firefox


Launch browser with proxy:
python launch_browser_proxy.py



Start mitmproxy (in separate terminal):
mitmproxy -s capture_squash.py -p 8081



Navigate to Squash TM in the launched browser

Option 2: Manual Browser ConfigurationIf automatic launch fails, configure manually:Chrome Manual Setup
Chrome Settings → Advanced → System → Open proxy settings
Set HTTP proxy: 127.0.0.1:8081
Set HTTPS proxy: 127.0.0.1:8081
Firefox Manual Setup
Firefox Preferences → Network Settings → Settings
Select Manual proxy configuration
HTTP Proxy: 127.0.0.1, Port: 8081
HTTPS Proxy: 127.0.0.1, Port: 8081
Check "Also use this proxy for HTTPS"
Files Explained
launch_browser_proxy.py - Main launcher script with both browser options
browser_config.py - Easy configuration file
squash_capture.py - mitmproxy script for capturing Squash TM data
TroubleshootingBrowser won't start
Check browser path in the script
Try manual configuration instead
Verify browser is installed
No traffic in mitmproxy
Verify proxy settings in browser
Check mitmproxy is running on port 8081
Try visiting http://httpbin.org/get first
Squash TM login issues
Some corporate networks block proxy traffic
Try disabling VPN if you have one
Check with IT about proxy restrictions
Switching BrowsersEdit browser_config.py:# For Chrome users:
USE_CHROME = True
USE_FIREFOX = False

# For Firefox users:  
USE_CHROME = False
USE_FIREFOX = True
Custom Browser PathsIf browsers are installed in non-standard locations:CHROME_CUSTOM_PATH = "/path/to/your/chrome"
FIREFOX_CUSTOM_PATH = "/path/to/your/firefox"
