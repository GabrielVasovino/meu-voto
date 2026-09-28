@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Sobe o Meu Voto aceitando os aparelhos da sua rede Tailscale (tablet, celular).
rem Outros aparelhos da rede Wi-Fi ou da internet continuam sem acesso.
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
python app\server.py --tailscale
pause
