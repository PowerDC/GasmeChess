
import os
import re
import io
import json
import urllib.request
import urllib.error
import streamlit as st
import chess
import chess.pgn
import random
from openai import OpenAI

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Ajedrez con IA + Terminal Gemini",
    page_icon="♟",
    layout="wide"
)

# --- CARGAR ESTILOS GLOBALES ---
def cargar_estilos():
    for archivo in ["board.css", "background.css", "sidebar.css", "buttons.css"]:
        ruta = os.path.join("styles", archivo)
        if os.path.exists(ruta):
            with open(ruta, "r", encoding="utf-8") as f:
                st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

cargar_estilos()               


# --- SIDEBAR DE PERSONALIZACIÓN ---
st.sidebar.markdown("## ⚙️ Personalización visual")
fondo_opcion = st.sidebar.radio(
    "Estilo de fondo",
    ["Madera Clásica 🪵", "Degradado Animado 🌈", "Vidrio Futurista 💠"],
    index=0
)

# Tamaño de casilla
cell_px = st.sidebar.slider("Tamaño casilla (px)", 44, 80, 60, 2)

# Modo IA automática
auto_ia = st.sidebar.toggle("Mover IA automáticamente", value=False)

# --- CSS SEGÚN ESTILO ---
if fondo_opcion.startswith("Madera"):
    fondo_css = """<style>.stApp{background-image:url('https://images.unsplash.com/photo-1614285371196-06d8b219b02d?auto=format&fit=crop&w=1600&q=80');background-size:cover;background-attachment:fixed;background-position:center}.stApp::before{content:"";position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:0}.main .block-container{position:relative;z-index:1;background:rgba(255,255,255,0.05);border-radius:12px;padding:2rem}</style>"""
elif fondo_opcion.startswith("Degradado"):
    fondo_css = """<style>.stApp{background:linear-gradient(-45deg,#2c3e50,#4ca1af,#2980b9,#8e44ad);background-size:400% 400%;animation:gradientBG 15s ease infinite}@keyframes gradientBG{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}.main .block-container{background:rgba(255,255,255,0.1);border-radius:12px;padding:2rem;box-shadow:0 4px 16px rgba(0,0,0,0.3)}</style>"""
else:
    fondo_css = """<style>.stApp{background:url('https://images.unsplash.com/photo-1606813902781-1d869ccf6f07?auto=format&fit=crop&w=1600&q=80') center/cover no-repeat fixed;backdrop-filter:blur(6px)}.main .block-container{background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.3);border-radius:12px;box-shadow:0 8px 32px 0 rgba(31,38,135,0.37);backdrop-filter:blur(10px);padding:2rem}</style>"""
st.markdown(fondo_css, unsafe_allow_html=True)


# --- TÍTULO ---
st.title("♟️ Ajedrez vs IA que 'piensa'")
st.subheader("Desafía a OpenAI · LM Studio · Gemma")

# --- ESTADO INICIAL ---
def inicializar_estado():
    ss = st.session_state
    if "board" not in ss: ss.board = chess.Board()
    if "history" not in ss: ss.history = []
    if "sel_from" not in ss: ss.sel_from = None
    if "provider" not in ss: ss.provider = "openai"
    if "model_openai" not in ss: ss.model_openai = "gpt-4o-mini"
    if "model_lmstudio" not in ss: ss.model_lmstudio = ""
    if "model_gemma" not in ss: ss.model_gemma = ""
    if "lmstudio_base_url" not in ss: ss.lmstudio_base_url = "http://localhost:1234/v1"
    if "orientation_white" not in ss: ss.orientation_white = True
    if "models_cache_bump" not in ss: ss.models_cache_bump = 0
    if "pending_promo_move_uci" not in ss: ss.pending_promo_move_uci = None
    if "pending_promo_side" not in ss: ss.pending_promo_side = None
    if "openai_client" not in ss: ss.openai_client = None
    if "lmstudio_client" not in ss: ss.lmstudio_client = None
    if "openai_key" not in ss: ss.openai_key = None
    if "lmstudio_base_url_cached" not in ss: ss.lmstudio_base_url_cached = None

inicializar_estado()
board: chess.Board = st.session_state.board

# --- SIDEBAR MODELOS ---
PROVEEDORES = ["openai", "lmstudio", "gemma"]
PROVEEDOR_NOMBRE = {"openai": "OpenAI", "lmstudio": "LM Studio", "gemma": "Gemma (LM Studio)"}
PROVEEDOR_AUTOR = {"openai": "OpenAI", "lmstudio": "LM Studio", "gemma": "Gemma"}

st.sidebar.markdown("## ♟️ Motor de IA")
if st.session_state.provider not in PROVEEDORES:
    st.session_state.provider = "openai"
proveedor = st.sidebar.selectbox(
    "Proveedor",
    PROVEEDORES,
    index=PROVEEDORES.index(st.session_state.provider),
    format_func=lambda x: PROVEEDOR_NOMBRE[x]
)
st.session_state.provider = proveedor

# --- RED Y MODELOS ---
def http_get_json(url: str, timeout: float = 5.0):
    try:
        req = urllib.request.Request(url, headers={"Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"Error de red al consultar {url}: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Respuesta no-JSON desde {url}") from e

@st.cache_data(show_spinner=False)
def listar_modelos_openai_cached(api_key: str, bump: int):
    try:
        client_tmp = OpenAI(api_key=api_key)
        resp = client_tmp.models.list()
        ids = [m.id for m in getattr(resp,"data",[])] or [getattr(m,"id",None) for m in resp]
        ids = [i for i in ids if i]
        return sorted(ids)
    except Exception as e:
        st.sidebar.warning(f"OpenAI modelos error: {e}")
        return []

@st.cache_data(show_spinner=False)
def listar_modelos_lmstudio_cached(base_url: str, bump: int):
    base_url = (base_url or "").rstrip("/")
    if not base_url: return []
    try:
        data = http_get_json(f"{base_url}/models")
        if isinstance(data, dict) and "data" in data:
            return [m.get("id") for m in data["data"] if isinstance(m, dict) and m.get("id")]
    except Exception:
        pass
    return []

def configurar_cliente_y_modelo():
    ss = st.session_state
    prov = ss.provider
    if prov == "openai":
        api_key = st.sidebar.text_input("OPENAI_API_KEY", value=os.getenv("OPENAI_API_KEY",""), type="password").strip()
        if not api_key:
            st.warning("Introduce tu clave OpenAI.")
            st.stop()
            raise SystemExit("Falta OPENAI_API_KEY. Ejecuta con: streamlit run GameChessGemini.py")
        if ss.openai_client is None or ss.get("openai_key") != api_key:
            ss.openai_client = OpenAI(api_key=api_key)
            ss.openai_key = api_key
        modelos = listar_modelos_openai_cached(api_key.strip(), ss.models_cache_bump) if api_key.strip() else []
        if modelos:
            ss.model_openai = st.sidebar.selectbox(
                "Modelo OpenAI",
                modelos,
                index=(modelos.index(ss.model_openai) if ss.model_openai in modelos else 0)
            )
        else:
            ss.model_openai = st.sidebar.text_input("Modelo OpenAI (manual)", value=ss.model_openai)
        return ss.openai_client, ss.model_openai

    base_url = st.sidebar.text_input("LM Studio base_url", value=ss.lmstudio_base_url, help="http://localhost:1234/v1")
    if st.sidebar.button("Actualizar lista"):
        ss.models_cache_bump += 1
    modelos = listar_modelos_lmstudio_cached(base_url.strip(), ss.models_cache_bump) if base_url.strip() else []

    if ss.lmstudio_client is None or ss.get("lmstudio_base_url_cached") != base_url:
        ss.lmstudio_client = OpenAI(base_url=(base_url.strip() or "http://localhost:1234/v1"), api_key="lm-studio")
        ss.lmstudio_base_url_cached = base_url
    ss.lmstudio_base_url = base_url

    if prov == "lmstudio":
        if modelos:
            ss.model_lmstudio = st.sidebar.selectbox(
                "Modelo LM Studio",
                modelos,
                index=(modelos.index(ss.model_lmstudio) if ss.model_lmstudio in modelos else 0)
            )
        else:
            ss.model_lmstudio = st.sidebar.text_input("Modelo LM Studio (manual)", value=ss.model_lmstudio)
        return ss.lmstudio_client, ss.model_lmstudio
    else:  # gemma
        gemmas = [m for m in modelos if "gemma" in (m or "").lower()]
        if gemmas:
            ss.model_gemma = st.sidebar.selectbox(
                "Modelo Gemma",
                gemmas,
                index=(gemmas.index(ss.model_gemma) if ss.model_gemma in gemmas else 0)
            )
        else:
            st.sidebar.info("No se detectaron modelos Gemma. Carga uno en LM Studio y pulsa 'Actualizar lista'.")
            ss.model_gemma = st.sidebar.text_input("Modelo Gemma (manual)", value=ss.model_gemma)
        return ss.lmstudio_client, ss.model_gemma

client, MODEL_NAME = configurar_cliente_y_modelo()

# --- UTILIDADES AJEDREZ ---
UNICODE_PIECES = {'P':'♙','N':'♘','B':'♗','R':'♖','Q':'♕','K':'♔','p':'♟','n':'♞','b':'♝','r':'♜','q':'♛','k':'♚'}

VALORES = {chess.PAWN:100, chess.KNIGHT:320, chess.BISHOP:330, chess.ROOK:500, chess.QUEEN:900, chess.KING:0}

def evaluar_posicion(b: chess.Board) -> int:
    """Score > 0 favorece a Blancas."""
    score = 0
    for sq in chess.SQUARES:
        p = b.piece_at(sq)
        if not p:
            continue
        val = VALORES[p.piece_type]
        score += val if p.color == chess.WHITE else -val

    # Movilidad ambos bandos
    turn_orig = b.turn
    b.turn = chess.WHITE
    movilidad_blancas = sum(1 for _ in b.legal_moves)
    b.turn = chess.BLACK
    movilidad_negras = sum(1 for _ in b.legal_moves)
    b.turn = turn_orig

    score += (movilidad_blancas - movilidad_negras)
    return score


def elegir_mejor_movimiento_local(b: chess.Board) -> chess.Move:
    sign = 1 if b.turn == chess.WHITE else -1
    best_score = -10**9
    best_move = None
    for m in b.legal_moves:
        b.push(m)
        sc = sign * evaluar_posicion(b)
        b.pop()
        if sc > best_score:
            best_score, best_move = sc, m
    return best_move or random.choice(list(b.legal_moves))


def legal_targets(from_sq: int) -> list[chess.Move]:
    return [m for m in board.legal_moves if m.from_square == from_sq] if from_sq is not None else []


def legal_moves_san(b: chess.Board) -> list[str]:
    return [b.san(m) for m in b.legal_moves]


def normalize_promotion_auto(move: chess.Move) -> chess.Move:
    if board.piece_at(move.from_square) and board.piece_at(move.from_square).piece_type == chess.PAWN:
        if chess.square_rank(move.to_square) in (0,7) and move.promotion is None:
            return chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
    return move


def es_promo_candidata(m: chess.Move, b: chess.Board) -> bool:
    p = b.piece_at(m.from_square)
    return p and p.piece_type == chess.PAWN and chess.square_rank(m.to_square) in (0, 7)


def solicitar_jugada_modelo(fen: str, ultimo_mov: str | None) -> str:
    legales = legal_moves_san(board)
    lista = ", ".join(legales)

    system_msg = (
        "Eres un asistente que JUEGA AJEDREZ. "
        "Debes responder exclusivamente con UNA jugada en notación SAN de la lista provista. "
        "No expliques nada. No añadas punto final."
    )
    user_msg = f"""
Posición (FEN): {fen}
Turno: {'Blancas' if board.turn==chess.WHITE else 'Negras'}
Último movimiento rival: {(ultimo_mov.split(':')[-1].strip() if ultimo_mov else 'Ninguno')}
Jugadas legales (SAN): {lista}

Responde SOLO con una jugada de la lista, exactamente igual."""
    try:
        chat = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=8,
            stop=["\n"],
        )
        texto = (chat.choices[0].message.content or "").strip()
        candidato = (
            texto.replace("`", "").replace("…", "").replace("...", "").strip().rstrip(".").split()[0]
        )
        if candidato in legales:
            return candidato
        base = candidato.rstrip("+#!?")
        if base in legales:
            return base
        return board.san(elegir_mejor_movimiento_local(board))
    except Exception as e:
        st.warning(f"Falló modelo ({e}), usando heurística.")
        return board.san(elegir_mejor_movimiento_local(board))


def aplicar_movimiento(move: chess.Move, san_label: str | None = None, autor: str = "Humano"):
    san = san_label or board.san(move)
    board.push(move)
    st.session_state.history.append(f"{autor}: {san}")
    st.session_state.sel_from = None


# --- COLORES CASILLAS ---
def color_base_casilla(sq: int) -> str:
    f = chess.square_file(sq)
    r = chess.square_rank(sq)
    return "#FFFFFF" if (r + f) % 2 == 0 else "#696969"


def color_casilla(sq: int, is_selected: bool, is_target: bool) -> str:
    if is_selected:
        return "#1e90ff"
    if is_target:
        return "#add8ff"
    return color_base_casilla(sq)


def color_texto(bg: str) -> str:
    if bg in ("#1e90ff", "#add8ff"):
        return "#000"
    bg_clean = bg.lstrip("#")
    if len(bg_clean) == 6:
        r = int(bg_clean[0:2], 16)
        g = int(bg_clean[2:4], 16)
        b = int(bg_clean[4:6], 16)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        return "#000" if lum > 150 else "#fff"
    return "#000"


# --- INTERFAZ ---
st.markdown("### Tablero interactivo")
col1, col2 = st.columns([2, 1])

with col1:
    if st.button("🔄 Rotar Tablero"):
        st.session_state.orientation_white = not st.session_state.orientation_white
    
    orientation = st.session_state.orientation_white
    selected_sq_name = st.session_state.sel_from
    selected_sq = chess.parse_square(selected_sq_name) if selected_sq_name else None
    
    highlight_moves = [m for m in board.legal_moves if m.from_square == selected_sq] if selected_sq is not None else []
    highlight_targets = {m.to_square for m in highlight_moves}
    
    last_f = last_t = None
    if board.move_stack:
        m = board.peek()
        last_f, last_t = m.from_square, m.to_square

    ranks = range(7, -1, -1) if orientation else range(0, 8)
    files = range(0, 8) if orientation else range(7, -1, -1)

    st.markdown('<div class="chess-area">', unsafe_allow_html=True)
    
    for r in ranks:
        # 1. Aplicamos el desplazamiento de la ilusión por fila
        row_offset_class = f"row-offset-{r % 4}"
        st.markdown(f'<div class="chess-row {row_offset_class}">', unsafe_allow_html=True)
        
        cols = st.columns(8, gap="small")
        for idx, f in enumerate(files):
            sq = chess.square(f, r)
            piece = board.piece_at(sq)
            sq_name = chess.square_name(sq)
            
            # Clase base: Blanco o Negro
            base_color_class = "light" if (chess.square_rank(sq) + chess.square_file(sq)) % 2 == 0 else "dark"
            
            # Clases de estado
            state_class = ""
            if sq == selected_sq: state_class = "selected"
            elif sq in highlight_targets: state_class = "target"
            elif sq in (last_f, last_t): state_class = "last-move"
            
            btn_key = f"sq_{sq_name}_{len(board.move_stack)}"
            label = UNICODE_PIECES.get(piece.symbol(), "") if piece else ("●" if sq in highlight_targets else " ")
            
            with cols[idx]:
                # 2. El div envuelve al botón y le pasa las clases
                st.markdown(f'<div class="chess-square {base_color_class} {state_class}">', unsafe_allow_html=True)
                clicked = st.button(label, key=btn_key, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)

                if clicked:
                    if selected_sq is None:
                        if piece and piece.color == board.turn:
                            st.session_state.sel_from = sq_name
                            st.rerun()
                    else:
                        if sq == selected_sq:
                            st.session_state.sel_from = None
                        else:
                            move = next((m for m in board.legal_moves if m.from_square == selected_sq and m.to_square == sq), None)
                            if move:
                                # Promoción auto a dama si llega al final
                                if piece_from := board.piece_at(selected_sq):
                                    if piece_from.piece_type == chess.PAWN and chess.square_rank(sq) in (0,7):
                                        move.promotion = chess.QUEEN
                                aplicar_movimiento(move, board.san(move), "Humano")
                            else:
                                if piece and piece.color == board.turn:
                                    st.session_state.sel_from = sq_name
                                else:
                                    st.session_state.sel_from = None
                        st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True) # Cierra chess-row
    
    st.markdown('</div>', unsafe_allow_html=True) # Cierra chess-area

    # Forzar el alto de los botones dinámicamente según el slider cell_px
    st.markdown(f"<style>.chess-square button {{ height: {cell_px}px !important; }}</style>", unsafe_allow_html=True)

with col2:
    prov_txt = PROVEEDOR_NOMBRE.get(st.session_state.provider, st.session_state.provider)
    st.markdown(f"### Modelo actual: {prov_txt} · {MODEL_NAME or '(sin modelo)'}")

    if board.is_game_over():
        res = "Final: "
        if board.is_checkmate():
            res += "Jaque mate."
        elif board.is_stalemate():
            res += "Tablas por ahogado."
        elif board.is_insufficient_material():
            res += "Tablas (material insuficiente)."
        elif board.is_seventyfive_moves():
            res += "Regla de 75 movimientos."
        elif board.is_fivefold_repetition():
            res += "Cinco repeticiones."
        else:
            res += "Resultado por otras reglas."
        st.info(res)
    else:
        if board.can_claim_threefold_repetition():
            st.info("Puedes reclamar tablas por triple repetición.")
        if board.can_claim_fifty_moves():
            st.info("Puedes reclamar tablas por regla de 50 movimientos.")

        if st.button("🤖 Pedir jugada a IA"):
            if st.session_state.pending_promo_move_uci:
                st.warning("Resuelve la promoción pendiente antes de pedir jugada a la IA.")
            else:
                ultimo = st.session_state.history[-1] if st.session_state.history else None
                jugada_san = solicitar_jugada_modelo(board.fen(), ultimo)
                if jugada_san:
                    try:
                        move = board.parse_san(jugada_san)
                    except Exception:
                        move = None
                    if move and move in board.legal_moves:
                        aplicar_movimiento(
                            move,
                            jugada_san,
                            PROVEEDOR_AUTOR.get(st.session_state.provider, st.session_state.provider)
                        )
                        st.success(f"La IA juega: {jugada_san}")
                        st.rerun()
                    else:
                        st.error(f"Jugada inválida: {jugada_san}")
                else:
                    st.warning("La IA no ofreció jugada legal.")

    # Auto IA: si está habilitado y es el turno de la IA, pensar y mover
    if auto_ia and not board.is_game_over() and not st.session_state.pending_promo_move_uci:
        # Suponemos que el humano empezó (blancas) y la IA responde cuando le toca.
        ultimo = st.session_state.history[-1] if st.session_state.history else None
        jugada_san = solicitar_jugada_modelo(board.fen(), ultimo)
        try:
            move = board.parse_san(jugada_san)
            if move in board.legal_moves:
                aplicar_movimiento(
                    move,
                    jugada_san,
                    PROVEEDOR_AUTOR.get(st.session_state.provider, st.session_state.provider)
                )
                st.rerun()
        except Exception as e:
            st.error(f"Jugada IA inválida: {jugada_san} ({e})")

    st.markdown("### Historial")
    for line in st.session_state.history[::-1]:
        st.write(line)

st.caption("Ejecuta: `streamlit run GameChessGemini.py`")


# --- CSS BOTONES TRANSPARENTES ---
st.markdown(
    """
<style>
div[data-testid="stButton"] > button { background: inherit !important; }
</style>
""",
    unsafe_allow_html=True,
)
