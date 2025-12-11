# test_audio.py
import streamlit as st
from time import sleep
import os
import base64
import random

# Importa las funciones de music_manager (que ya tienes tal cual)
from music_manager import (
    init_music,
    set_music_mode,
    trigger_accusation_sound,
    trigger_question_sound,
)

st.set_page_config(page_title="TEST AUDIO", layout="centered")
st.title("Test de audio CluedoGenAI (UI)")

# ---------- Inicialización (solo UI) ----------
# init_music() rellenará st.session_state.music_tracks y demás flags
init_music()

# Aseguramos clave para audio_enabled (para sortear bloqueo de autoplay)
if "audio_enabled" not in st.session_state:
    st.session_state.audio_enabled = False

# Botón explícito para permitir sonido
col_enable, _ = st.columns([1, 4])
with col_enable:
    if not st.session_state.audio_enabled:
        if st.button("Activar audio (click para permitir sonido)"):
            st.session_state.audio_enabled = True
            st.success("Audio activado. Si hay pistas, la música de fondo debería comenzar pronto.")

# Selector de modo
modo = st.radio("Modo musical:", ["Ambient", "Ending"], index=0)
if st.session_state.get("music_mode") != modo.lower():
    set_music_mode(modo.lower())

# Botones de prueba (marcan flags usando las funciones del manager)
col1, col2 = st.columns(2)
with col1:
    if st.button("Sonido de ACUSACIÓN", use_container_width=True):
        trigger_accusation_sound()
        st.success("Reproduciendo acusación...")

with col2:
    if st.button("Sonido de PREGUNTA", use_container_width=True):
        trigger_question_sound()
        st.info("Reproduciendo pregunta...")

st.write("Si no suena: revisa `assets/audio` y pulsa 'Activar audio'.")
st.write("DEBUG tracks (borra esta línea en producción):", st.session_state.get("music_tracks"))

# ---------- Utilidades locales para la UI ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def file_to_data_url(path: str) -> str | None:
    """
    Lee un archivo binario y devuelve una data URL 'data:audio/mp3;base64,...'
    Devuelve None si el archivo no existe o no se puede leer.
    """
    if not path or not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        b = f.read()
    b64 = base64.b64encode(b).decode()
    return f"data:audio/mp3;base64,{b64}"

def choose_random_path(paths: list[str]) -> str | None:
    if not paths:
        return None
    return random.choice(paths)

def _render_single_audio_tag_from_path(path: str) -> str:
    """
    Construye un tag <audio autoplay> para un sfx a partir de la ruta del fichero.
    """
    url = file_to_data_url(path)
    if not url:
        return ""
    html = f"""
    <audio autoplay style="display:none;">
      <source src="{url}" type="audio/mpeg">
    </audio>
    """
    return html

def _build_bg_player_html(mode: str, tracks: dict, audio_enabled: bool) -> str:
    """
    Construye el HTML/JS del reproductor de fondo usando data URLs.
    Si audio_enabled==False, arrancamos en muted para permitir autoplay en navegadores que lo permiten.
    """
    use_mode = (mode or "ambient").lower()
    if use_mode == "ending":
        bg_paths = tracks.get("ending", [])
    else:
        bg_paths = tracks.get("ambient", [])

    sources = []
    for p in bg_paths:
        url = file_to_data_url(p)
        if url:
            sources.append(f"\"{url}\"")

    if not sources:
        return ""

    sources_js_array = ",\n        ".join(sources)
    js_audio_enabled = "true" if audio_enabled else "false"

    html = f"""
    <audio id="bg-music" style="display:none;"></audio>
    <script>
      const bgSources = [
        {sources_js_array}
      ];
      const AUDIO_ENABLED = {js_audio_enabled};

      function playRandomBg() {{
        if (!bgSources.length) return;
        const idx = Math.floor(Math.random() * bgSources.length);
        const audio = document.getElementById("bg-music");
        if (!audio) return;
        audio.src = bgSources[idx];
        audio.play().catch(() => {{ }});
      }}

      const audioEl = document.getElementById("bg-music");
      if (audioEl) {{
        audioEl.onended = playRandomBg;
        audioEl.muted = !AUDIO_ENABLED;
        if (AUDIO_ENABLED) {{
          playRandomBg();
        }} else {{
          // intentar autoplay en modo muted (es más probable que el navegador lo permita)
          audioEl.muted = true;
          playRandomBg();
        }}
      }}
    </script>
    """
    return html

# ---------- Render del reproductor (llamar último) ----------
def render_music_player():
    tracks = st.session_state.get("music_tracks", {})
    if not tracks:
        return

    mode = st.session_state.get("music_mode", "ambient").lower()
    audio_enabled = bool(st.session_state.get("audio_enabled", False))

    # 1) Música de fondo
    bg_html = _build_bg_player_html(mode, tracks, audio_enabled)
    if bg_html:
        st.markdown(bg_html, unsafe_allow_html=True)

    # 2) SFX acusación (si procede)
    if st.session_state.get("music_accuse_pending", False):
        p = choose_random_path(tracks.get("accuse", []))
        if p:
            sfx_html = _render_single_audio_tag_from_path(p)
            if sfx_html:
                st.markdown(sfx_html, unsafe_allow_html=True)
        st.session_state.music_accuse_pending = False

    # 3) SFX pregunta (si procede)
    if st.session_state.get("music_question_pending", False):
        p = choose_random_path(tracks.get("question", []))
        if p:
            sfx_html = _render_single_audio_tag_from_path(p)
            if sfx_html:
                st.markdown(sfx_html, unsafe_allow_html=True)
        st.session_state.music_question_pending = False

# IMPORTANT: llamar siempre al final para que detecte los cambios de flags realizados por botones
render_music_player()

# pequeña pausa para mejorar estabilidad del render en algunos entornos
sleep(0.2)
