@echo off
chcp 65001 >nul
echo Ajustes de Ollama para ExamAgent (se guardan para el usuario actual):
echo  - Flash attention: menos memoria y mas velocidad en el contexto.
echo  - Cache KV cuantizada (q8_0): casi la mitad de memoria de contexto, sin perdida apreciable.
echo  - 2 peticiones en paralelo y 2 modelos cargados (modelo rapido + modelo de arbitraje).
setx OLLAMA_FLASH_ATTENTION 1 >nul
setx OLLAMA_KV_CACHE_TYPE q8_0 >nul
setx OLLAMA_NUM_PARALLEL 2 >nul
setx OLLAMA_MAX_LOADED_MODELS 2 >nul
echo.
echo Listo. Cierra Ollama (icono de la bandeja - Quit) y vuelve a abrirlo para aplicar los cambios.
pause
