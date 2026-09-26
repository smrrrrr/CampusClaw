"""应用配置：从环境变量 / .env 文件读取。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 数据库
    database_url: str = "sqlite:///./campusclaw.db"

    # JWT
    jwt_secret_key: str = "campusclaw-dev-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120  # 2 小时
    refresh_token_expire_days: int = 7
    temp_token_expire_minutes: int = 5

    # 短信验证码 Mock 模式
    sms_mock: bool = True

    # 生产环境关闭交互式 API 文档（/docs、/redoc、/openapi.json）
    enable_docs: bool = True

    # 学校缩写（初始密码规则：三位小写缩写 + 学号/工号后 6 位）
    school_abbr: str = "thu"

    # CORS
    frontend_origins: str = "http://localhost:3000"

    # Cookie
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    # 材料上传
    # 本地开发：uploads（相对 backend 工作目录）；Docker：/app/uploads
    upload_dir: str = "uploads"
    max_file_size_mb: int = 50
    # 允许的文件格式（MIME → 扩展名映射，用于前端 accept 与后端校验）
    allowed_extensions: str = "pdf,pptx,docx,jpg,png"

    # RAG 检索（add-rag-search）
    chunk_size: int = 500          # 文本分块长度（字符）
    chunk_overlap: int = 100       # 相邻分块重叠长度（字符）
    chunk_top_k: int = 12           # 相似度检索返回的分块数（提高后可覆盖更多相关材料）
    embed_dim: int = 512           # 字符 n-gram 哈希向量维度

    # AI 解题助手：DeepSeek 生成（openai 兼容接口）
    deepseek_api_key: str = ""               # 为空则 AI 生成降级为提示
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout: float = 60             # 单次请求超时（秒）
    deepseek_temperature: float = 0.3        # 偏低以贴合资料、减少编造

    @property
    def frontend_origin_list(self) -> list[str]:
        return [o.strip() for o in self.frontend_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
