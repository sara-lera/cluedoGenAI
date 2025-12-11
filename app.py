# app.py
from __future__ import annotations

import json
import os
import sys
from html import escape, unescape
from typing import Dict, List, Optional
from datetime import datetime
import re
import signal
from dotenv import load_dotenv
import streamlit as st

from music_manager import scan_tracks, choose_random_bg_url, choose_random_sfx_url
import time
import random
import base64

if sys.platform == "win32":
    if not hasattr(signal, "SIGHUP"):
        signal.SIGHUP = signal.SIGTERM
        signal.SIGTSTP = signal.SIGTERM
        signal.SIGCONT = signal.SIGTERM

load_dotenv() # Tiene en cuenta el archivo .env que contiene la API key


# ✅ Añadir la carpeta src al PYTHONPATH para que se vea cluedogenai
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))    # .../genAICluedo/cluedoGenAI
SRC_PATH = os.path.join(CURRENT_DIR, "src")                 # .../genAICluedo/cluedoGenAI/src

if SRC_PATH not in sys.path:
    # MUY IMPORTANTE: insertarlo al principio, antes de site-packages
    sys.path.insert(0, SRC_PATH)

from cluedogenai.crew import Cluedogenai  # noqa: E402


TOTAL_QUESTIONS = 10
MAX_TURNS_IN_SUMMARY = 3
CREW_TOPIC = "AI Murder Mystery"


# =========================
#  CREW HELPERS
# =========================

def _extract_json(text: str) -> Optional[dict]:
    """Intenta extraer un JSON de un texto que puede tener 'Thought:' + ```json ...``` + más cosas."""
    if not text:
        return None

    text = text.strip()

    # 1) Si empieza con fences ```... intentar como antes
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
        try:
            return json.loads(candidate)
        except Exception:
            # Si falla, caemos a la heurística general de abajo
            text = candidate

    # 2) Buscar el primer bloque {...} dentro del texto, aunque haya "Thought:" antes
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = text[start : end + 1]
        try:
            return json.loads(json_str)
        except Exception:
            pass

    # Si no pudimos parsear nada
    return None

def _strip_html_tags(text: str) -> str:
    """Elimina cualquier etiqueta HTML básica de un string."""
    if not text:
        return ""
    # quita cosas tipo <div ...>, </p>, <br>, etc.
    text = re.sub(r"<[^>]+>", " ", text)
    # colapsar espacios múltiples
    text = " ".join(text.split())
    return text.strip()

def _safe_get_task_raw(task_obj) -> Optional[str]:
    """
    Intenta extraer un string "crudo" de un TaskOutput de CrewAI,
    probando atributos comunes (raw, output, value, etc.).
    """
    if task_obj is None:
        return None
    for attr in ("raw", "output", "value", "result", "content"):
        if hasattr(task_obj, attr):
            val = getattr(task_obj, attr)
            if isinstance(val, str) and val.strip():
                return val
    # Si no hay atributo claro, cae a str()
    s = str(task_obj)
    return s if s.strip() else None


def generate_case_with_crew() -> Dict:
    """
    Usa la Crew (create_scene_blueprint + define_characters) para generar:
    - escena inicial
    - lista de sospechosos

    Devuelve un dict con el formato esperado por el juego:

    {
      "victim": ...,
      "time": ...,
      "place": ...,
      "cause": ...,
      "context": ...,
      "suspects": [
         {
           "name": ...,
           "role": ...,
           "personality": ...,
           "secret": ...,
           "guilty": bool,
         },
         ...
      ],
      "guilty_name": "Nombre del culpable"
    }

    Si algo sale mal, lanza una excepción.
    """
    # Defaults por si la escena no devuelve algo usable
    base_case = {
        "victim": "Unknown Victim",
        "time": "Sometime past midnight",
        "place": "An almost empty tech office",
        "cause": "Suspicious accident with smart equipment",
        "context": (
            "A storm hits the city. Backup power keeps the systems barely alive. "
            "Only a handful of employees remain inside for a late-night push before a major demo."
        ),
    }

    # Estado inicial enviado al crew
    game_state = json.dumps(base_case, ensure_ascii=False)
    player_action = (
        "We are starting the game. Design the opening scene and the full cast of suspects. "
        "Focus on a tech-office, late-night atmosphere."
    )

    crew_inputs = {
        "topic": CREW_TOPIC,
        "current_year": str(datetime.now().year),
        "game_state": game_state,
        "player_action": player_action,
    }

    crew = Cluedogenai().setup_crew()

    try:
        result = crew.kickoff(inputs=crew_inputs)
    except Exception as e:
        raise RuntimeError(f"Error calling CrewAI: {e}") from e

    # Según versión de CrewAI, tasks_output puede ser lista o dict
    tasks_out = getattr(result, "tasks_output", None)
    if tasks_out is None:
        tasks_out = getattr(result, "raw", None) or {}

    scene_blueprint_json = None
    characters_json = None

    try:
        # Caso: lista de TaskOutput
        if isinstance(tasks_out, list):
            for t in tasks_out:
                raw = _safe_get_task_raw(t)
                data = _extract_json(raw) if raw else None
                if not data:
                    continue
                # Escena
                if "scene_id" in data and "present_characters" in data:
                    scene_blueprint_json = data
                # Personajes (acepta guilty_name o killer_id)
                if "suspects" in data:
                    characters_json = data


        # Caso: dict mapeado por nombre de task
        elif isinstance(tasks_out, dict):
            scene_task = tasks_out.get("create_scene_blueprint")
            char_task = tasks_out.get("define_characters")

            if scene_task is not None:
                raw_scene = _safe_get_task_raw(scene_task)
                scene_blueprint_json = _extract_json(raw_scene)

            if char_task is not None:
                raw_chars = _safe_get_task_raw(char_task)
                characters_json = _extract_json(raw_chars)

    except Exception as e:
        raise RuntimeError(f"Error parsing Crew output: {e}") from e

    # Guardamos la escena y personajes en session_state para el diálogo
    if scene_blueprint_json is not None:
        st.session_state.scene_blueprint = scene_blueprint_json
    if characters_json is not None:
        st.session_state.characters = characters_json

    # =========================
    #  AJUSTAR CASE CON LA ESCENA
    # =========================
    if scene_blueprint_json:
        # 1) Victim: intentar sacar el nombre desde present_characters
        victim = None
        present_chars = scene_blueprint_json.get("present_characters") or []
        for ch in present_chars:
            # Ejemplo: "Leon Vance (Victim - deceased)"
            if "Victim" in ch or "victim" in ch:
                victim = ch.split("(")[0].strip()
                break

        # Si no lo encontramos ahí, buscamos en el summary (e.g. "body of Leon Vance")
        summary = scene_blueprint_json.get("summary", "") or ""
        if not victim and summary:
            m = re.search(r"body of ([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)*)", summary)
            if m:
                victim = m.group(1)

        if victim:
            base_case["victim"] = victim

        # 2) Place: usar location de la escena si existe
        location = scene_blueprint_json.get("location")
        if location:
            base_case["place"] = location

        # 3) Time: usar la primera frase/frase inicial del summary (p.ej. "Past midnight")
        if summary:
            first_sentence = summary.split(".")[0].strip()
            if first_sentence:
                # Si hay coma, nos quedamos con lo anterior (ej. "Past midnight")
                time_phrase = first_sentence.split(",")[0].strip()
                if time_phrase:
                    base_case["time"] = time_phrase

        # 4) Cause: si en el summary o visible_clues aparece "electrocuted"
        cause = None
        if "electrocut" in summary.lower():
            cause = "Electrocution involving the Nexus-Smart-Hub prototype"
        else:
            visible_clues = scene_blueprint_json.get("visible_clues") or []
            clues_text = " ".join(visible_clues)
            if "electrocut" in clues_text.lower():
                cause = "Electrocution during the server room incident"

        if cause:
            base_case["cause"] = cause

        # 5) Contexto: usamos summary + hidden_tension si está
        hidden_tension = scene_blueprint_json.get("hidden_tension", "")
        if summary and hidden_tension:
            base_case["context"] = f"{summary} {hidden_tension}"
        elif summary:
            base_case["context"] = summary
        elif hidden_tension:
            base_case["context"] = hidden_tension

    # =========================
    #  VALIDAR Y NORMALIZAR SOSPECHOSOS
    # =========================
    if not characters_json or "suspects" not in characters_json:
        raise RuntimeError("Crew did not return a valid 'characters' JSON with 'suspects'.")

    suspects_raw = characters_json["suspects"]
    if not isinstance(suspects_raw, list) or len(suspects_raw) == 0:
        raise RuntimeError("Characters JSON has an empty or invalid 'suspects' list.")

    # Resolver nombre del culpable
    guilty_name = characters_json.get("guilty_name")
    if not guilty_name:
        killer_id = characters_json.get("killer_id")
        if killer_id:
            for s in suspects_raw:
                if s.get("id") == killer_id:
                    guilty_name = s.get("name")
                    break

    if not guilty_name:
        # Como fallback, mira quién tiene guilty = True
        for s in suspects_raw:
            if s.get("guilty") is True:
                guilty_name = s.get("name")
                break

    if not guilty_name:
        raise RuntimeError("Could not determine guilty_name from characters JSON.")

    # Normalizamos sospechosos al formato interno del juego
    suspects = []
    for s in suspects_raw:
        suspects.append(
            {
                "name": s.get("name", "Unknown Suspect"),
                "role": s.get("role", ""),
                "personality": s.get("personality", ""),
                "secret": s.get("secret") or s.get("secret_motivation", ""),
                "guilty": bool(
                    s.get("guilty", False)
                    or s.get("name") == guilty_name
                    or s.get("id") == characters_json.get("killer_id")
                ),
            }
        )

    # Construimos el case final que usará todo el juego
    case = dict(base_case)
    case["suspects"] = suspects
    case["guilty_name"] = guilty_name

    return case


def call_crew_for_answer(
    case: Dict,
    suspect_name: str,
    history: List[Dict],
    question: str,
) -> str:
    """
    Usa la Crew para generar la respuesta del sospechoso.
    NO hay llamada directa a Gemini: todo va por CrewAI.
    Si falla (por cuota, etc.), devuelve un texto en personaje en vez de romper el juego.
    """
    system_prompt = build_system_prompt(case, suspect_name)
    user_prompt = build_user_prompt(suspect_name, history, question)

    # Opcional: añadimos contexto extra si lo tenemos
    scene_blueprint = st.session_state.get("scene_blueprint")
    characters = st.session_state.get("characters")

    crew_inputs = {
        "topic": CREW_TOPIC,
        "current_year": str(datetime.now().year),
        "game_state": system_prompt,
        "player_action": user_prompt,
        "scene_blueprint": json.dumps(scene_blueprint, ensure_ascii=False) if scene_blueprint else "",
        "characters": json.dumps(characters, ensure_ascii=False) if characters else "",
    }

    try:
        crew = Cluedogenai().dialogue_crew()
        result = crew.kickoff(inputs=crew_inputs)

        # 1) Intentar leer tasks_output (forma moderna de CrewAI)
        tasks_out = getattr(result, "tasks_output", None) or getattr(result, "raw", None)

        data = None

        if isinstance(tasks_out, list):
            # Solo tenemos una tarea (generate_suspect_dialogue)
            for t in tasks_out:
                raw = _safe_get_task_raw(t)
                if not raw:
                    continue
                candidate = _extract_json(raw)
                if isinstance(candidate, dict) and "spoken_text" in candidate:
                    data = candidate
                    break

        elif isinstance(tasks_out, dict):
            # Por si viniera mapeado por nombre de tarea
            t = tasks_out.get("generate_suspect_dialogue")
            if t is not None:
                raw = _safe_get_task_raw(t)
                data = _extract_json(raw)

        # 2) Si hemos conseguido JSON con spoken_text, lo devolvemos
        if isinstance(data, dict):
            spoken = data.get("spoken_text") or data.get("answer") or data.get("text")
            if spoken:
                return spoken.strip()

        # 3) Fallback: intentar extraer JSON de str(result)
        raw_fallback = str(result)
        data_fb = _extract_json(raw_fallback)
        if isinstance(data_fb, dict):
            spoken_fb = data_fb.get("spoken_text") or data_fb.get("answer") or data_fb.get("text")
            if spoken_fb:
                return spoken_fb.strip()

        # 4) Último fallback: devolver un string recortado
        answer_text = raw_fallback.strip()
        if len(answer_text) > 400:
            answer_text = answer_text[:400] + "..."
        return answer_text

    except Exception as e:
        msg = str(e)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "Quota exceeded" in msg:
            return (
                "The overhead lights flicker and the network icon turns red. "
                "«Systems are throttled… you won’t get more out of me right now,» "
                "the suspect says, dodging your question."
            )
        return (
            "The suspect just stares back at you. "
            "Something in the system glitched and they refuse to answer."
        )
    
def trigger_question_sound_local() -> None:
    tracks = st.session_state.get("music_tracks", {})
    pool = tracks.get("question", []) or []
    if not pool:
        print("No question SFX available")
        return
    path = random.choice(pool)
    try:
        with open(path, "rb") as f:
            st.session_state.last_sfx_bytes = f.read()
            st.session_state._sfx_key = f"sfx_{int(time.time()*1000)}"
    except Exception:
        st.session_state.last_sfx_bytes = None


def trigger_accusation_sound_local() -> None:
    tracks = st.session_state.get("music_tracks", {})
    pool = tracks.get("accuse", []) or []
    if pool:
        path = random.choice(pool)
        try:
            with open(path, "rb") as f:
                st.session_state.last_sfx_bytes = f.read()
                st.session_state._sfx_key = f"sfx_{int(time.time()*1000)}"
        except Exception:
            st.session_state.last_sfx_bytes = None
    else:
        print("No accusation SFX available")

    # ---- nueva lógica: marcar ending pendiente en session_state ----
    ending_pool = tracks.get("ending", []) or []
    if ending_pool:
        chosen_ending = random.choice(ending_pool)
        # guardamos la data-url en memoria para que el JS la tome cuando el SFX acabe
        try:
            st.session_state._pending_ending_data_url = file_to_data_url(chosen_ending)
            # flag para que el JS sepa que debe cambiar la pista al finalizar
            st.session_state._pending_switch_to_ending = True
        except Exception:
            st.session_state._pending_ending_data_url = None
            st.session_state._pending_switch_to_ending = False
    else:
        st.session_state._pending_switch_to_ending = False



# Helper: convertir UN SOLO fichero a data URL (solo cuando se vaya a reproducir como bg loop)
def file_to_data_url(path: str) -> Optional[str]:
    """
    Lee el fichero mp3 y devuelve una data URL 'data:audio/mp3;base64,...'
    Devuelve None si no existe o falla.
    ADVERTENCIA: leer un mp3 de 3 minutos puede ocupar varios MB en memoria, por eso
    lo hacemos solo para la pista de fondo seleccionada (no para todas).
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            b = f.read()
        return "data:audio/mp3;base64," + base64.b64encode(b).decode()
    except Exception:
        return None

def toggle_music_enabled() -> None:
    """
    Alterna st.session_state.music_enabled entre True/False.
    Si activamos música y no hay bg_path calculado, forzamos init_music_state_local.
    """
    cur = st.session_state.get("music_enabled", False)
    st.session_state.music_enabled = not cur

    # Si activamos y no tenemos pistas inicializadas, inicializamos
    if st.session_state.music_enabled and "music_tracks" not in st.session_state:
        try:
            init_music_state_local()
        except Exception:
            # no queremos que errores de audio rompan la app
            pass

    # Si acabamos de activar la música, preparar data URL de fondo (lazy -> ahora)
    if st.session_state.get("music_enabled", False):
        bg_path = st.session_state.get("bg_path")
        if bg_path and not st.session_state.get("bg_data_url"):
            # Generamos la data URL ahora para minimizar latencia cuando aparezca el audio
            try:
                st.session_state.bg_data_url = file_to_data_url(bg_path)
            except Exception:
                st.session_state.bg_data_url = None




# =========================
#  GAME STATE & LOGIC
# =========================

def init_music_state_local(audio_dir: Optional[str] = None) -> None:
    """
    Inicializa tracks (rutas locales) en st.session_state.
    No convierte a data URL todavía.
    """
    if "music_tracks" in st.session_state:
        return

    tracks = scan_tracks(audio_dir)  # devuelve rutas locales según tu music_manager
    st.session_state.music_tracks = tracks
    st.session_state.music_mode = "ambient"
    # Elegimos una pista de background *ruta local* al azar (si existe)
    bg_path = None
    ambient_list = tracks.get("ambient", []) or []
    if ambient_list:
        bg_path = random.choice(ambient_list)
    st.session_state.bg_path = bg_path
    st.session_state.bg_data_url = None  # se calculará bajo demanda
    st.session_state.last_sfx_bytes = None
    st.session_state._sfx_key = None


def init_game_state() -> None:
    if "case" in st.session_state:
        return

    try:
        case = generate_case_with_crew()
        st.session_state.case = case
        st.session_state.guilty_name = case["guilty_name"]
        st.session_state.histories = {s["name"]: [] for s in case["suspects"]}
        st.session_state.remaining_questions = TOTAL_QUESTIONS
        st.session_state.game_over = False
        st.session_state.accused = None
        st.session_state.outcome = None
        st.session_state.selected_suspect = case["suspects"][0]["name"]
        st.session_state.accuse_choice = case["suspects"][0]["name"]
        st.session_state.crew_failed = False
        st.session_state.crew_error = ""
    except Exception as e:
        # Si Crew falla, marcamos estado de error y no iniciamos el juego
        st.session_state.crew_failed = True
        st.session_state.crew_error = f"Failed to generate the case with CrewAI: {e}"
        # case vacío para evitar KeyError
        st.session_state.case = {}
        st.session_state.histories = {}
        st.session_state.remaining_questions = 0
        st.session_state.game_over = True
        st.session_state.accused = None
        st.session_state.outcome = None
        st.session_state.selected_suspect = None
        st.session_state.accuse_choice = None


def reset_game() -> None:
    st.session_state.clear()
    st.rerun()


def _suspects_basic_lines(case: Dict) -> List[str]:
    lines = []
    for s in case.get("suspects", []):
        lines.append(f"**{s['name']}** — {s['role']}  \n_{s['personality']}_")
    return lines


def render_sidebar(disabled: bool) -> None:
    case = st.session_state.case

    with st.sidebar:
        # Control de la musica
        if "music_enabled" not in st.session_state:
            st.session_state.music_enabled = False

        # Botón que alterna el estado
        st.button("Turn music on" if not st.session_state.music_enabled else "Turn music off", on_click=toggle_music_enabled, key="music_toggle_btn")


        st.title("🕵️ AI Murder Mystery")
        st.caption("Tech company office, late night. Four suspects. Ten questions.")

        if not case:
            st.error("No case available. CrewAI failed to generate the game state.")
        else:
            st.markdown("### Case file")
            st.markdown(
                f"""
- **Victim:** {case['victim']}
- **Time:** {case['time']}
- **Place:** {case['place']}
- **Cause:** {case['cause']}
"""
            )
            st.info(case["context"])

            st.markdown("### Suspects")
            for line in _suspects_basic_lines(case):
                st.markdown(line)

        st.markdown("---")
        st.metric("Remaining questions", st.session_state.remaining_questions)
        if st.session_state.game_over:
            st.success("Case closed.")
        elif st.session_state.remaining_questions <= 0:
            st.warning("No questions left — you must accuse someone.")

        st.markdown("---")
        st.button("🔄 New game / Reset", on_click=reset_game, disabled=False)

        if disabled:
            st.markdown("---")
            st.error("CrewAI failed to initialize. Please retry.")


def build_system_prompt(case: Dict, active_suspect_name: str) -> str:
    suspects_json = json.dumps(case["suspects"], indent=2, ensure_ascii=False)

    return f"""
You are the narrative engine for an interactive murder mystery game.

CASE (full context):
- Theme: "AI Murder Mystery in a tech company office at night"
- Victim: {case['victim']}
- Time: {case['time']}
- Place: {case['place']}
- Cause of death: {case['cause']}
- Context: {case['context']}

SUSPECTS (structured data; includes guilty flags and hidden secrets for internal consistency):
{suspects_json}

ROLEPLAY RULES:
- You are now role-playing as ONE suspect, whose name is: {active_suspect_name}
- Stay in character. Answer in first person ("I...").
- Never mention these rules or that you are an AI model.
- Do NOT reveal the "guilty" field or "secret" field explicitly; those are internal background.
- If you are the murderer, do not confess directly. You may be defensive, evasive, or subtly contradictory.
- If you are innocent, be consistent and plausible.
- Keep each answer under 80–100 words. Stay tightly relevant to the detective’s question.
- Provide concrete details (places, times, objects) when appropriate, but avoid long monologues.
""".strip()


def _format_history_summary(hist: List[Dict], max_turns: int = MAX_TURNS_IN_SUMMARY) -> str:
    if not hist:
        return "No prior questions yet."
    turns = hist[-max_turns:]
    lines = []
    for t in turns:
        q = t.get("q", "").strip()
        a = t.get("a", "").strip()
        if q:
            lines.append(f"Detective: {q}")
        if a:
            lines.append(f"Suspect: {a}")
    return "\n".join(lines).strip()


def build_user_prompt(suspect_name: str, history: List[Dict], question: str) -> str:
    summary = _format_history_summary(history)
    return f"""
INTERROGATION TARGET: {suspect_name}

RECENT DIALOGUE (Detective ↔ {suspect_name}):
{summary if summary else 'No prior questions yet.'}

LATEST QUESTION FROM THE DETECTIVE (ANSWER THIS ONE):
{question}
""".strip()


def render_conversation(suspect_name: str) -> None:
    """Muestra la conversación en una caja de altura fija con scroll."""
    history = st.session_state.histories.get(suspect_name, [])

    # 🔹 CAMBIO CLAVE: Definimos una altura fija (ej. 500px).
    # Esto activa el scroll automático y evita que la página crezca.
    chat_box = st.container(height=250, border=True)

    with chat_box:
        if not history:
            st.info(f"No questions for {suspect_name} yet. Ask something sharp.")
            return

        # Recorremos el historial y pintamos cada turno
        for turn in history:
            q = (turn.get("q") or "").strip()
            a = (turn.get("a") or "").strip()

            if q:
                with st.chat_message("user", avatar="🕵️"):
                    st.markdown(q)

            if a:
                with st.chat_message("assistant", avatar="🧩"):
                    st.markdown(a)


def handle_question_submit(suspect_name: str, question: str, disabled: bool) -> None:
    q = (question or "").strip()
    if not q:
        return
    if disabled:
        st.warning("CrewAI is currently unavailable; you cannot ask more questions.")
        return
    if st.session_state.game_over:
        st.info("The case is closed. Start a new game to ask more questions.")
        return
    if st.session_state.remaining_questions <= 0:
        st.warning("No questions left — you must accuse someone.")
        return


    case = st.session_state.case
    history = st.session_state.histories[suspect_name]

    st.session_state.remaining_questions -= 1

    # Mostrar un spinner mientras el sospechoso "piensa"
    with st.spinner(f"{suspect_name} is thinking…"):
        answer = call_crew_for_answer(case, suspect_name, history, q)

    # 🔹 Limpiar entidades HTML y etiquetas por si la crew devuelve HTML crudo
    answer = unescape(answer or "")
    answer = _strip_html_tags(answer)

    history.append({"q": q, "a": answer})


    # 🔊 Suena sonido de pregunta
    # Reproducir SFX de pregunta (se guardará la URL en session_state y render_music_player la reproducirá)
    try:
        trigger_question_sound_local()
    except Exception:
        print("Error triggering question sound")
        # evitar que fallos de audio rompan el flujo
        pass

    if st.session_state.remaining_questions <= 0:
        st.toast("No questions left. Time to accuse someone.", icon="⚖️")



def _generate_epilogue(case: Dict, accused_name: str, won: bool, guilty_name: str) -> str:
    """
    Epílogo sin LLM: sólo texto generado a mano para no depender de más modelos.
    """
    if won:
        return (
            f"You lay out the last contradiction, and the room goes quiet.\n\n"
            f"{guilty_name} stops arguing and starts calculating. The storm outside fades, "
            "but the weight of the evidence doesn’t. Logs, timelines — "
            "all of it lines up in a single, sharp line pointing at them.\n\n"
            "Security walks them out. The office hums back to life, one monitor at a time."
        )
    else:
        return (
            f"You point the finger at {accused_name}, and the room tenses. "
            f"For a moment it almost fits — almost.\n\n"
            f"But the loose ends remain. Somewhere in the logs, in the access patterns, "
            f"in the off-by-one timestamp, {guilty_name} slips away clean.\n\n"
            "The storm passes. The case closes on paper, but not in your head."
        )


def handle_accusation(accused_name: str, disabled: bool) -> None:
    if disabled:
        st.warning("CrewAI is currently unavailable; you cannot close the case.")
        return
    if st.session_state.game_over:
        return
    
    case = st.session_state.case
    guilty_name = st.session_state.guilty_name
    
    # 🔊 Suena sonido de acusación
    # Reproducir SFX de acusación y cambiar bg a ending (si corresponde)
    try:
        trigger_accusation_sound_local()
    except Exception:
        pass

    st.session_state.accused = accused_name
    won = accused_name == guilty_name
    epilogue = _generate_epilogue(case, accused_name, won, guilty_name)

    st.session_state.outcome = {
        "won": won,
        "accused": accused_name,
        "guilty": guilty_name,
        "epilogue": epilogue,
    }
    st.session_state.game_over = True


# =========================
#  STREAMLIT RENDER
# =========================

def render_game() -> None:
    """Dibuja todo el juego en Streamlit (sin set_page_config)."""
    init_game_state()

    crew_failed = st.session_state.get("crew_failed", False)
    disabled = crew_failed

    if crew_failed:
        st.markdown(
            """
            <div style="display:flex; align-items:baseline; gap:12px;">
              <h1 style="margin:0;">AI Murder Mystery</h1>
              <div style="opacity:0.75; font-size:14px;">CrewAI failed to generate the case.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.error(st.session_state.get("crew_error", "Unknown error while calling CrewAI."))
        st.button("🔄 Retry generating case", on_click=reset_game)
        return
    
    #Music
    init_music_state_local(audio_dir=None)


    # Header
    st.markdown(
        """
        <div style="display:flex; align-items:baseline; gap:12px;">
          <h1 style="margin:0;">AI Murder Mystery</h1>
          <div style="opacity:0.75; font-size:14px;">Interrogate. Observe contradictions. Accuse.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 🔹 Sidebar con fichas de caso + sospechosos
    render_sidebar(disabled=disabled)

    case = st.session_state.case

    # 🔹 NUEVO: Brief de la historia en el centro
    if case:
        st.markdown(
            f"""
            <div style="
                margin: 12px 0 22px 0;
                padding: 14px 18px;
                border-radius: 18px;
                background: #f1f5f9;
                border: 1px solid rgba(148,163,184,0.6);
            ">
              <div style="
                  font-size: 11px;
                  text-transform: uppercase;
                  letter-spacing: 0.12em;
                  color: #64748b;
                  margin-bottom: 6px;
              ">
                Case briefing
              </div>
              <div style="font-size: 15px; color:#0f172a;">
                <p style="margin: 0 0 4px 0;">
                  <b>Victim:</b> {escape(case.get('victim', 'Unknown victim'))}
                </p>
                <p style="margin: 0 0 4px 0;">
                  <b>Time:</b> {escape(case.get('time', 'Unknown time'))}
                  &nbsp;·&nbsp;
                  <b>Place:</b> {escape(case.get('place', 'Unknown place'))}
                </p>
                <p style="margin: 0 0 6px 0;">
                  <b>Cause:</b> {escape(case.get('cause', 'Unknown cause'))}
                </p>
                <p style="margin: 4px 0 0 0; font-size: 14px; color:#1e293b;">
                  {escape(case.get('context', ''))}
                </p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    suspect_names = [s["name"] for s in case["suspects"]]


    # Main UI
    col_left, col_right = st.columns([1.2, 0.8], vertical_alignment="top")

    with col_left:
        st.subheader("Interrogation")
        selected = st.selectbox(
            "Choose a suspect",
            suspect_names,
            key="selected_suspect",
            disabled=disabled,
            help="Pick someone to question. You have limited total questions.",
        )

        s_map = {s["name"]: s for s in case["suspects"]}
        s = s_map[selected]
        st.markdown(
            f"""
            <div style="border:1px solid rgba(0,0,0,0.08); border-radius:16px; padding:12px 14px; background:#ffffff;">
              <div style="font-weight:700; font-size:16px;">{escape(s['name'])}</div>
              <div style="opacity:0.8;">{escape(s['role'])} · {escape(s['personality'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("#### Conversation")
        render_conversation(selected)

        can_ask = (not st.session_state.game_over) and (st.session_state.remaining_questions > 0) and (not disabled)

        if st.session_state.remaining_questions <= 0 and not st.session_state.game_over:
            st.warning("You are out of questions. Make your accusation below.")

        user_q = st.chat_input(
            "Ask a question… (keep it specific)",
            disabled=not can_ask,
        )
        if user_q is not None:
            handle_question_submit(selected, user_q, disabled=disabled)
            st.rerun()

    with col_right:
        st.subheader("Accuse")
        st.caption("When you’re ready—or when you run out of questions—make your accusation.")

        accuse_disabled = disabled or st.session_state.game_over
        st.selectbox(
            "Accuse one suspect",
            suspect_names,
            key="accuse_choice",
            disabled=accuse_disabled,
        )

        btn_disabled = accuse_disabled
        if st.button("⚖️ Accuse now", disabled=btn_disabled, use_container_width=True):
            handle_accusation(st.session_state.accuse_choice, disabled=disabled)
            st.rerun()

        st.markdown("---")

        if st.session_state.outcome:
            out = st.session_state.outcome
            if out["won"]:
                st.success(f"Correct. **{out['accused']}** is the murderer.")
            else:
                st.error(
                    f"Wrong. You accused **{out['accused']}** — the real murderer was **{out['guilty']}**."
                )
            st.markdown("#### Epilogue")
            st.write(out["epilogue"])

        elif st.session_state.game_over:
            st.info("Case closed. Reset to play again.")

        with st.expander("Tips", expanded=False):
            st.markdown(
                """
                - Ask about **timestamps**, **locations**, and **what they touched** (devices, doors, logs).
                - Look for **subtle contradictions**: wrong sequence, wrong room, wrong system.
                """
            )
    
        # Pon esto justo ANTES de llamar a render_music_player_local() en render_game()
    if st.session_state.get("last_sfx_bytes"):
        print(f"🔊 SFX Bytes cargados en memoria: {len(st.session_state.last_sfx_bytes)} bytes")
    else:
        print("🔇 No hay bytes de SFX en session_state")

    render_music_player_local()


def bytes_to_data_url(b: bytes) -> Optional[str]:
    """Convierte bytes MP3 a data URL 'data:audio/mp3;base64,...'."""
    if not b:
        return None
    try:
        return "data:audio/mp3;base64," + base64.b64encode(b).decode()
    except Exception:
        return None


def render_music_player_local() -> None:
    """
    Renderiza background y reproduce SFX usando autoplay nativo HTML.
    Esto evita problemas si Streamlit bloquea la ejecución de scripts JS.
    """
    if not st.session_state.get("music_enabled", False):
        return

    # --- BACKGROUND AUDIO ---
    bg_data_url = st.session_state.get("bg_data_url")
    bg_path = st.session_state.get("bg_path")

    # Lazy loading del background
    if not bg_data_url and bg_path:
        bg_data_url = file_to_data_url(bg_path)
        st.session_state.bg_data_url = bg_data_url

    # Render del Background
    if bg_data_url:
        # ID bg_audio para que el script (si funciona) lo encuentre
        html_bg = f"""
        <audio id="bg_audio" src="{bg_data_url}" loop autoplay controls style="width:100%; margin-bottom: 10px;">
        </audio>
        """
        st.markdown(html_bg, unsafe_allow_html=True)

    # --- SFX AUDIO ---
    sfx_bytes = st.session_state.get("last_sfx_bytes")
    
    if sfx_bytes:
        sfx_data_url = bytes_to_data_url(sfx_bytes)
        if sfx_data_url:
            sfx_id = f"sfx_{int(time.time()*1000)}"
            
            html_sfx = f"""
            <audio id="{sfx_id}" src="{sfx_data_url}" autoplay="true" style="display:none;"></audio>
            
            <script>
                // Intentamos hacer el efecto ducking (bajar volumen fondo), 
                // pero si este script no corre, al menos el sonido sonará por el 'autoplay' de arriba.
                (function() {{
                    var bg = document.getElementById("bg_audio");
                    var sfx = document.getElementById("{sfx_id}");
                    
                    if(bg && sfx) {{
                        var originalVol = bg.volume;
                        bg.volume = 0.2; // Bajar volumen música
                        
                        sfx.onended = function() {{
                            bg.volume = originalVol; // Restaurar volumen
                        }};
                    }}
                }})();
            </script>
            """
            # Usamos un contenedor vacío para inyectarlo y que no "ensucie" la UI visualmente
            st.markdown(html_sfx, unsafe_allow_html=True)

        # Limpiar inmediatamente para que no se repita en el siguiente rerun
        st.session_state.last_sfx_bytes = None
        st.session_state._sfx_key = None




def main() -> None:
    st.set_page_config(page_title="AI Murder Mystery", page_icon="🕵️", layout="wide")

    render_game()


if __name__ == "__main__":
    main()
