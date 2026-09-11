"""
Gera o executável RoboMT5.exe (Windows) com PyInstaller.

    python empacotar.py              # gera dist/RoboMT5/RoboMT5.exe
    python empacotar.py --atalho     # e cria um atalho na Área de Trabalho
    python empacotar.py --console    # variante com console (útil para depurar)

O programa fica em dist/RoboMT5/ (pasta completa — copie a pasta inteira se
quiser levá-lo para outro computador). configuracao.json, resultados/ e
registros/ são criados ao lado do .exe na primeira execução.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
NOME = "RoboMT5"


def garantir_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Instalando PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def construir(console: bool) -> str:
    for pasta in ("build", os.path.join("dist", NOME)):
        shutil.rmtree(os.path.join(RAIZ, pasta), ignore_errors=True)
    comando = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", NOME,
        "--onedir", "--console" if console else "--windowed",
        "--paths", RAIZ,
        # módulos importados dinamicamente (import dentro de função) que o PyInstaller não enxerga sozinho
        "--hidden-import", "ia.filtro_ml",
        "--hidden-import", "interface.janela",
        "--hidden-import", "sklearn.ensemble",
        "--hidden-import", "sklearn.model_selection",
        "--hidden-import", "sklearn.tree._utils",
        "--hidden-import", "sklearn.utils._typedefs",
        "--hidden-import", "sklearn.utils._cython_blas",
        "--hidden-import", "sklearn.neighbors._partition_nodes",
        "--collect-submodules", "dominio.estrategias",
        "--collect-submodules", "infraestrutura",
        "--exclude-module", "matplotlib",
        "--exclude-module", "PyQt5",
        "--exclude-module", "PySide2",
        "--exclude-module", "IPython",
        "--exclude-module", "pytest",
        os.path.join(RAIZ, "main.py"),
    ]
    if os.path.exists(os.path.join(RAIZ, "icone.ico")):
        comando += ["--icon", os.path.join(RAIZ, "icone.ico")]
    subprocess.check_call(comando, cwd=RAIZ)
    return os.path.join(RAIZ, "dist", NOME, f"{NOME}.exe")


def criar_atalho(exe: str) -> str:
    """Atalho na Área de Trabalho (usa o WScript.Shell do Windows via PowerShell)."""
    area = os.path.join(os.path.expanduser("~"), "Desktop")
    atalho = os.path.join(area, f"{NOME}.lnk")
    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{atalho}'); "
              f"$s.TargetPath = '{exe}'; $s.WorkingDirectory = '{os.path.dirname(exe)}'; "
              f"$s.Description = 'Robô MT5 — seleção automática de estratégias'; $s.Save()")
    subprocess.check_call(["powershell", "-NoProfile", "-Command", script])
    return atalho


def main() -> None:
    parser = argparse.ArgumentParser(description="Empacota o Robô MT5 como executável.")
    parser.add_argument("--console", action="store_true", help="gera a variante com console (para depurar)")
    parser.add_argument("--atalho", action="store_true", help="cria um atalho na Área de Trabalho")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("O empacotamento foi preparado para Windows (onde o MetaTrader 5 roda).")
    garantir_pyinstaller()
    exe = construir(args.console)
    print(f"\nExecutável gerado: {exe}")
    if args.atalho:
        print(f"Atalho criado: {criar_atalho(exe)}")


if __name__ == "__main__":
    main()
