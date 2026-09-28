@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Liga o tablet (cabo USB, depuracao USB ativada) ao app que roda neste computador.
adb start-server >nul 2>&1
adb get-state >nul 2>&1
if errorlevel 1 (
  echo Tablet nao encontrado. Confira o cabo USB e se a depuracao USB esta ligada.
  echo Se aparecer "Permitir depuracao USB?" na tela do tablet, toque em Permitir.
  pause
  exit /b 1
)
adb reverse tcp:8765 tcp:8765
netstat -ano | findstr /r /c:":8765 .*LISTENING" >nul
if errorlevel 1 (
  python -m pip install --quiet --disable-pip-version-check -r requirements.txt
  start "Meu Voto 2026" python app\server.py --sem-navegador
  timeout /t 4 /nobreak >nul
)
adb shell am start -a android.intent.action.VIEW -d http://localhost:8765 >nul
echo Pronto: o Meu Voto abriu no tablet. Deixe o cabo ligado e a janela do servidor aberta.
timeout /t 5 >nul
