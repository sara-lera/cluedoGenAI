#!/usr/bin/env python3
"""
test_music_manager.py

Script de prueba para comprobar que music_manager scan_tracks / selección funcionan.

Uso:
  python test_music_manager.py              # solo muestra resumen y rutas
  python test_music_manager.py --make-html  # además crea music_test_player.html con bg + sfx incrustados

Requisitos:
  - Tener music_manager.py en el mismo proyecto y la carpeta assets/audio/ con mp3.
"""

import os
import sys
import argparse
import base64
import random
from typing import Optional

# Intentamos importar el módulo music_manager del proyecto
try:
    import music_manager
except Exception as e:
    print("ERROR: no se pudo importar music_manager. Asegúrate de que music_manager.py está en el proyecto.")
    print("Detalles:", e)
    sys.exit(1)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024.0:
            return f"{n:3.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}TB"


def file_size(path: str) -> Optional[int]:
    try:
        return os.path.getsize(path)
    except Exception:
        return None


def file_to_data_url(path: str) -> Optional[str]:
    """Convierte un fichero MP3 a data URL 'data:audio/mp3;base64,...'."""
    if not path or not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        b = f.read()
    return "data:audio/mp3;base64," + base64.b64encode(b).decode()


def main(make_html: bool):
    print("=== test_music_manager ===")
    # 1) Escanear usando music_manager.scan_tracks()
    # Le damos None para que use el default (assets/audio)
    tracks = music_manager.scan_tracks()
    print("Tracks escaneados (por categoría):")
    for cat in ("ambient", "ending", "accuse", "question"):
        lst = tracks.get(cat, []) or []
        print(f"  - {cat}: {len(lst)} archivos")
        # mostrar hasta 3 ejemplos
        for i, p in enumerate(lst[:3], start=1):
            size = file_size(p)
            print(f"      {i}. {p}  ({human_size(size) if size else '??'})")

    # 2) Elegir bg y sfx (si existen)
    bg = music_manager.choose_random_bg_url(tracks, mode="ambient")
    sfx_q = music_manager.choose_random_sfx_url(tracks, kind="question")
    sfx_a = music_manager.choose_random_sfx_url(tracks, kind="accuse")

    print("\nSelección aleatoria (muestra):")
    if bg:
        print(f"  - background (ambient): {bg}  size={human_size(file_size(bg) or 0)}")
    else:
        print("  - background (ambient): (no disponible)")

    if sfx_q:
        print(f"  - sfx (question): {sfx_q}  size={human_size(file_size(sfx_q) or 0)}")
    else:
        print("  - sfx (question): (no disponible)")

    if sfx_a:
        print(f"  - sfx (accuse): {sfx_a}  size={human_size(file_size(sfx_a) or 0)}")
    else:
        print("  - sfx (accuse): (no disponible)")

    # 3) Si no hay pistas, salimos
    total = sum(len(tracks.get(c, []) or []) for c in ("ambient", "ending", "accuse", "question"))
    if total == 0:
        print("\nNo se han encontrado mp3 en assets/audio/. Coloca archivos con prefijos ambient_, ending_, accuse_, question_.")
        return

    # 4) Opción: crear HTML incrustando bg + sfx como data URLs
    if make_html:
        if not bg:
            print("\nNo hay pista de background para generar el HTML. Abortando generación del HTML.")
            return
        # Elegimos un sfx preferible: question si existe, si no accuse, si no ninguno -> None
        sfx = sfx_q or sfx_a

        # Convertimos a data-URL (advertencia: puede ocupar varios MB)
        print("\nConvirtiendo archivos a data-URL (esto puede tardar y usar memoria)...")
        bg_data = file_to_data_url(bg)
        sfx_data = file_to_data_url(sfx) if sfx else None

        if bg_data is None:
            print("Error al leer/conertir el bg a data URL.")
            return

        html_lines = [
            "<!doctype html>",
            "<html>",
            "<head><meta charset='utf-8'><title>Music Manager Test</title></head>",
            "<body>",
            "<h2>Music Manager Test Player</h2>",
            "<p>Background (loop, autoplay). Si el navegador bloquea autoplay, pulsa play manualmente.</p>",
            f"<audio id='bg' src='{bg_data}' loop controls autoplay style='width:100%;'></audio>",
        ]

        if sfx_data:
            html_lines += [
                "<hr>",
                "<p>SFX (reproducir manualmente o usando el botón):</p>",
                f"<audio id='sfx' src='{sfx_data}' controls style='width:100%;'></audio>",
                "<p><button onclick=\"document.getElementById('sfx').play();\">Play SFX</button></p>",
            ]

        html_lines += [
            "<hr>",
            "<p>Nota: este HTML embebe los mp3 como data URLs. El archivo final puede ser grande.</p>",
            "</body></html>",
        ]

        out_path = os.path.join(os.getcwd(), "music_test_player.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(html_lines))

        # Mostrar info
        html_size = os.path.getsize(out_path)
        print(f"\nHTML generado en: {out_path}  (tamaño: {human_size(html_size)})")
        print("Ábrelo en el navegador para probar la reproducción (puede que el navegador bloquee autoplay hasta que interactúes).")
    else:
        print("\nModo interactivo desactivado. Si quieres generar un HTML de prueba ejecuta con --make-html.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test music_manager (scan, choose bg/sfx, optional HTML player).")
    parser.add_argument("--make-html", action="store_true", help="Generar music_test_player.html incrustando bg + sfx como data URLs (puede ser grande).")
    args = parser.parse_args()
    main(make_html=args.make_html)
