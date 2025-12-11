import os
import random
from typing import Dict, List, Optional

# Directorio local por defecto (relativo al módulo)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "assets", "audio")


def scan_tracks(audio_dir: Optional[str] = None, base_url: Optional[str] = None) -> Dict[str, List[str]]:
    """
    Escanea la carpeta local audio_dir (si existe) y devuelve un dict con listas de URLs (si base_url dado)
    o rutas locales si no se pasa base_url.

    Retorno:
      {
        "ambient": [<url_or_path>, ...],
        "ending":  [...],
        "accuse":  [...],
        "question": [...]
      }

    Requisitos de nombre de fichero (para categorizar):
      ambient_*.mp3, ending_*.mp3, accuse_*.mp3, question_*.mp3
    """
    dir_to_scan = audio_dir or AUDIO_DIR

    ambient: List[str] = []
    ending: List[str] = []
    accuse: List[str] = []
    question: List[str] = []

    if not os.path.isdir(dir_to_scan):
        # Devuelve vacíos si no existe el directorio local; esto es útil si solo vas a usar URLs externas.
        return {"ambient": ambient, "ending": ending, "accuse": accuse, "question": question}

    for fname in sorted(os.listdir(dir_to_scan)):
        if not fname.lower().endswith(".mp3"):
            continue
        full_path = os.path.join(dir_to_scan, fname)
        # Si te han pasado un base_url, construimos la URL pública usando el nombre de fichero
        if base_url:
            # Asumimos que has subido los mp3 con el mismo nombre al bucket/host y son accesibles en base_url/<filename>
            url = base_url.rstrip("/") + "/" + fname
            entry = url
        else:
            entry = full_path

        lower = fname.lower()
        if lower.startswith("ambient_"):
            ambient.append(entry)
        elif lower.startswith("ending_"):
            ending.append(entry)
        elif lower.startswith("accuse_"):
            accuse.append(entry)
        elif lower.startswith("question_"):
            question.append(entry)

    return {"ambient": ambient, "ending": ending, "accuse": accuse, "question": question}


# Selección aleatoria de background / sfx a partir del dict devuelto por scan_tracks

def choose_random_bg_url(tracks: Dict[str, List[str]], mode: str = "ambient") -> Optional[str]:
    """
    Devuelve una URL (o ruta) aleatoria de las pistas de fondo para 'mode' ('ambient' o 'ending').
    """
    use_mode = (mode or "ambient").lower()
    if use_mode == "ending":
        pool = tracks.get("ending", []) or []
    else:
        pool = tracks.get("ambient", []) or []
    return random.choice(pool) if pool else None


def choose_random_sfx_url(tracks: Dict[str, List[str]], kind: str) -> Optional[str]:
    """
    Devuelve una URL (o ruta) aleatoria de SFX ('accuse' o 'question').
    """
    k = (kind or "").lower()
    if k == "accuse":
        pool = tracks.get("accuse", []) or []
    elif k == "question":
        pool = tracks.get("question", []) or []
    else:
        pool = []
    return random.choice(pool) if pool else None
