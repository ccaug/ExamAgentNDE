from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ollama_base_url: str = 'http://127.0.0.1:11434'
    # Modelos por nivel de la cascada. Vacío = elegir automáticamente según el hardware.
    fast_model: str = ''
    strong_model: str = ''
    keep_alive: str = '30m'
    ollama_timeout: int = 600
    eval_workers: int = 0            # 0 = automático (2 con GPU, 1 en CPU)
    fast_ctx: int = 2048
    strong_ctx: int = 4096
    strong_think_tokens: int = 1500  # tope de tokens de razonamiento del modelo fuerte
    conf_agree: float = 0.6          # confianza mínima si el modelo rápido coincide con GES
    conf_alone: float = 0.9          # confianza mínima si no hay nota GES con la que contrastar
    low_confidence: float = 0.6      # umbral para marcar "dudosa" en el panel
    time_budget_s: int = 0           # 0 = sin límite; si >0, la escalada se detiene al agotarse
    write_explanations: bool = True
    overwrite_explanations: bool = False
    host: str = '127.0.0.1'
    port: int = 8765
    data_dir: str = './data'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


settings = Settings()
