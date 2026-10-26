"""生成/复用 MCP 服务令牌，同步到忽略入库的环境文件；不显示值。"""
from pathlib import Path
import secrets


def configure():
    root = Path(__file__).resolve().parents[1]
    env = root / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    token = next((line.partition("=")[2].strip().strip('"').strip("'") for line in lines if line.partition("=")[0].strip() == "MCP_AUTH_TOKEN"), "")
    token = token or secrets.token_urlsafe(32)
    jwt_key = next((line.partition("=")[2].strip().strip('"').strip("'") for line in lines if line.partition("=")[0].strip() == "JWT_SECRET_KEY"), "")
    jwt_key = jwt_key or secrets.token_urlsafe(48)
    for path in (env, root / "backend" / ".env"):
        content = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        content = [line for line in content if line.partition("=")[0].strip() != "MCP_AUTH_TOKEN"]
        if path == env:
            content = [line for line in content if line.partition("=")[0].strip() != "JWT_SECRET_KEY"]
            content.append("JWT_SECRET_KEY=" + jwt_key)
        path.write_text("\n".join(content) + "\nMCP_AUTH_TOKEN=" + token + "\n", encoding="utf-8")
    print("MCP credential configured in ignored environment files (value not displayed).")
    print("Docker JWT signing key configured in ignored root environment file (value not displayed).")


if __name__ == "__main__":
    configure()
