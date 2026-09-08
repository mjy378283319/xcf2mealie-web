"""容器健康检查：Flask 在监听且能响应，即视为健康。

开启 Basic Auth（WEB_USER/WEB_PASSWORD）后，首页对未认证请求返回 401。
这属于「服务正常、需要登录」，不能判为 unhealthy，否则 Docker/Unraid 会把容器标红。
"""
import os
import sys
import urllib.error
import urllib.request

url = "http://127.0.0.1:" + os.environ.get("PORT", "9926") + "/"

try:
    urllib.request.urlopen(url, timeout=3)
except urllib.error.HTTPError as exc:
    if exc.code in (200, 401, 403):
        # 401/403 = 需要登录，服务本身是好的
        sys.exit(0)
    print("unexpected HTTP status:", exc.code, file=sys.stderr)
    sys.exit(1)
except Exception as exc:
    print("healthcheck failed:", exc, file=sys.stderr)
    sys.exit(1)

sys.exit(0)
