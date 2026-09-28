@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Coloca a versão pública do Meu Voto na internet a partir deste computador (sem login, sem guardar votos).
rem O endereço aparece nesta janela. Para encerrar, feche a janela ou tecle Ctrl+C.
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
python app\publicar.py
pause
