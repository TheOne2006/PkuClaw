from __future__ import annotations

import os
import sys

import lark_oapi as lark
from lark_oapi.api.auth.v3 import InternalTenantAccessTokenRequest


def main() -> int:
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        print("Missing FEISHU_APP_ID or FEISHU_APP_SECRET.", file=sys.stderr)
        return 2

    client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
    request = InternalTenantAccessTokenRequest.builder().build()
    response = client.auth.v3.tenant_access_token.internal(request)
    if not response.success():
        print(f"Feishu token check failed: code={response.code}, msg={response.msg}", file=sys.stderr)
        return 1

    print("Feishu token check ok.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
