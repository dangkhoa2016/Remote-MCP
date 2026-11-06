"""Manual controller smoke check; never prints the control token."""
import json
import os
import urllib.request

request = urllib.request.Request("http://127.0.0.1:8766/v1/control/devices",
                                 headers={"X-Control-Token": os.environ["KRW_CONTROL_TOKEN"]})
with urllib.request.urlopen(request, timeout=5) as response:
    print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
