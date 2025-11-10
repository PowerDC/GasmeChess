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
    page_title="Ajedrez con IA que 'piensa'",
    page_icon="♟",
    layout="wide"
)

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
st.subheader("Desafía a OpenAI · Ollama · Gemma")

# --- ESTADO INICIAL ---
def inicializar_estado():
    ss = st.session_state
    if "board" not in ss: ss.board = chess.Board()
    if "history" not in ss: ss.history = []
    if "sel_from" not in ss: ss.sel_from = None
    if "provider" not in ss: ss.provider = "openai"  # openai | ollama | gemma
    if "model_openai" not in ss: ss.model_openai = "gpt-4o-mini"
    if "model_ollama" not in ss: ss.model_ollama = "llama2:7b"
    if "model_gemma" not in ss: ss.model_gemma = "gemma:2b"
    if "ollama_base_url" not in ss: ss.ollama_base_url = "http://localhost:11434/v1"
    if "orientation_white" not in ss: ss.orientation_white = True
    if "models_cache_bump" not in ss: ss.models_cache_bump = 0
    if "pending_promo_move_uci" not in ss: ss.pending_promo_move_uci = None
    if "pending_promo_side" not in ss: ss.pending_promo_side = None
    if "openai_client" not in ss: ss.openai_client = None
    if "ollama_client" not in ss: ss.ollama_client = None
    if "openai_key" not in ss: ss.openai_key = None
    if "ollama_base_url_cached" not in ss: ss.ollama_base_url_cached = None

inicializar_estado()
board: chess.Board = st.session_state.board

# --- SIDEBAR MODELOS ---
st.sidebar.markdown("## ♟️ Motor de IA")
proveedor = st.sidebar.selectbox(
    "Proveedor",
    ["openai", "ollama", "gemma"],
    index=["openai","ollama","gemma"].index(st.session_state.provider),
    format_func=lambda x: "OpenAI" if x=="openai" else ("Ollama" if x=="ollama" else "Gemma (Ollama)")
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
def listar_modelos_ollama_cached(base_url: str, bump: int):
    base_url = (base_url or "").rstrip("/")
    if not base_url: return []
    try:
        data = http_get_json(f"{base_url}/models")
        if isinstance(data, dict) and "data" in data:
            return [m.get("id") for m in data["data"] if isinstance(m, dict)]
    except Exception:
        pass
    # Fallback tags
    try:
        root = base_url.split("/v1")[0]
        tags = http_get_json(f"{root}/api/tags")
        if isinstance(tags, dict) and "models" in tags:
            return [m.get("name") for m in tags["models"] if isinstance(m, dict)]
    except Exception:
        pass
    return []

def configurar_cliente_y_modelo():
    ss = st.session_state
    prov = ss.provider
    if prov == "openai":
        api_key = st.sidebar.text_input("OPENAI_API_KEY", value=os.getenv("OPENAI_API_KEY",""), type="password")
        if not api_key:
            st.warning("Introduce tu clave OpenAI.")
            st.stop()
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

    base_url = st.sidebar.text_input("Ollama base_url", value=ss.ollama_base_url, help="http://localhost:11434/v1")
    if st.sidebar.button("Actualizar lista"):
        ss.models_cache_bump += 1
    modelos = listar_modelos_ollama_cached(base_url.strip(), ss.models_cache_bump) if base_url.strip() else []

    if ss.ollama_client is None or ss.get("ollama_base_url_cached") != base_url:
        ss.ollama_client = OpenAI(base_url=(base_url.strip() or "http://localhost:11434/v1"), api_key="ollama")
        ss.ollama_base_url_cached = base_url
    ss.ollama_base_url = base_url

    if prov == "ollama":
        if modelos:
            ss.model_ollama = st.sidebar.selectbox(
                "Modelo Ollama",
                modelos,
                index=(modelos.index(ss.model_ollama) if ss.model_ollama in modelos else 0)
            )
        else:
            ss.model_ollama = st.sidebar.text_input("Modelo Ollama (manual)", value=ss.model_ollama)
        return ss.ollama_client, ss.model_ollama
    else:  # gemma
        gemmas = [m for m in modelos if "gemma" in (m or "").lower()]
        if gemmas:
            ss.model_gemma = st.sidebar.selectbox(
                "Modelo Gemma",
                gemmas,
                index=(gemmas.index(ss.model_gemma) if ss.model_gemma in gemmas else 0)
            )
        else:
            st.sidebar.info("No se detectaron modelos Gemma. Instala: ollama pull gemma:2b")
            ss.model_gemma = st.sidebar.text_input("Modelo Gemma (manual)", value=ss.model_gemma)
        return ss.ollama_client, ss.model_gemma

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
    if st.button("🔄 Cambiar orientación"):
        st.session_state.orientation_white = not st.session_state.orientation_white
    orientation_white = st.session_state.orientation_white

    selected_square = st.session_state.sel_from
    selected_from_sq = chess.parse_square(selected_square) if selected_square else None
    highlight_moves = legal_targets(selected_from_sq)
    highlight_targets = {m.to_square for m in highlight_moves}

    ranks = range(7, -1, -1) if orientation_white else range(0, 8)
    files = range(0, 8) if orientation_white else range(7, -1, -1)

    st.markdown('<div class="chess-area">', unsafe_allow_html=True)
    css_styles = []

    for r in ranks:
        cols = st.columns(8, gap="small")
        for idx, f in enumerate(files):
            sq = chess.square(f, r)
            piece = board.piece_at(sq)
            label_piece = UNICODE_PIECES.get(piece.symbol(), '') if piece else ''
            sq_name = chess.square_name(sq)

            is_selected = (sq == selected_from_sq)
            is_target = (sq in highlight_targets)
            bg = color_casilla(sq, is_selected, is_target)
            fg = color_texto(bg)
            key_btn = f"square_{sq_name}"
            wrap_id = f"wrap_{key_btn}"

            btn_label = label_piece if label_piece else ("●" if is_target else " ")

            with cols[idx]:
                st.markdown(f'<div id="{wrap_id}">', unsafe_allow_html=True)
                clicked = st.button(btn_label, key=key_btn, help=sq_name, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)

            # Acumular estilos CSS para inyectarlos todos juntos al final
            css_styles.append(f"""
                div#{wrap_id} > button {{
                    background-color: {bg} !important;
                    color: {fg} !important;
                    border: 1px solid #222 !important;
                    height: {cell_px}px;
                    font-size: {int(cell_px*0.5)}px;
                    line-height: {int(cell_px*0.5)}px;
                    padding: 0;
                    font-weight: 600;
                    box-shadow: none !important;
                    border-radius: 6px;
                    transition: all .15s ease-in-out;
                }}
                div#{wrap_id} > button:hover {{
                    transform: scale(1.05);
                    box-shadow: 0 0 8px rgba(0,0,0,.5);
                    filter: brightness(1.1);
                }}
                div#{wrap_id} > button:active {{
                    transform: scale(.97);
                    filter: brightness(.9);
                }}
            """)

            if clicked:
                if st.session_state.pending_promo_move_uci:
                    st.info("Primero resuelve la promoción pendiente.")
                    st.rerun()

                if selected_from_sq is None:
                    if piece and piece.color == board.turn:
                        st.session_state.sel_from = sq_name
                        st.rerun()
                else:
                    if sq == selected_from_sq:
                        st.session_state.sel_from = None
                        st.rerun()
                    else:
                        posibles = [m for m in highlight_moves if m.to_square == sq]
                        if posibles:
                            move0 = posibles[0]
                            if es_promo_candidata(move0, board) and move0.promotion is None:
                                st.session_state.pending_promo_move_uci = move0.uci()
                                st.session_state.pending_promo_side = 'Humano'
                                st.session_state.sel_from = None
                                st.rerun()
                            else:
                                move = normalize_promotion_auto(move0)
                                san = board.san(move)
                                aplicar_movimiento(move, san, "Humano")
                                st.rerun()
                        else:
                            piece2 = board.piece_at(sq)
                            if piece2 and piece2.color == board.turn:
                                st.session_state.sel_from = sq_name
                                st.rerun()

    # Inyectar todos los estilos de una sola vez
    st.markdown(f"<style>{''.join(css_styles)}</style>", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ... resto del código (promoción, movimiento manual, etc.) ...
    # --- Promoción pendiente UI ---
    if st.session_state.pending_promo_move_uci:
        st.markdown("#### Promoción requerida")
        promo_piece = st.selectbox("Promocionar a:", ["Dama", "Torre", "Alfil", "Caballo"], index=0)
        cpr1, cpr2 = st.columns(2)
        if cpr1.button("✅ Confirmar promoción"):
            promo_map = {"Dama": chess.QUEEN, "Torre": chess.ROOK, "Alfil": chess.BISHOP, "Caballo": chess.KNIGHT}
            base = chess.Move.from_uci(st.session_state.pending_promo_move_uci)
            move = chess.Move(base.from_square, base.to_square, promotion=promo_map[promo_piece])
            san = board.san(move)
            aplicar_movimiento(move, san, st.session_state.pending_promo_side or "Humano")
            st.session_state.pending_promo_move_uci = None
            st.session_state.pending_promo_side = None
            st.rerun()
        if cpr2.button("❌ Cancelar"):
            st.session_state.pending_promo_move_uci = None
            st.session_state.pending_promo_side = None
            st.rerun()

    st.markdown("### Movimiento manual (SAN)")
    mov_input = st.text_input("Introduce jugada (ej: e4, Nf3, O-O, exd5)")
    c1, c2, c3 = st.columns(3)
    if c1.button("✅ Aplicar jugada"):
        if mov_input.strip():
            try:
                move = board.parse_san(mov_input.strip())
                # Si es promoción sin pieza elegida, fuerza a dama por defecto
                if es_promo_candidata(move, board) and move.promotion is None:
                    move = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
                aplicar_movimiento(move, mov_input.strip(), "Humano")
                st.rerun()
            except Exception as e:
                st.error(f"Jugada inválida: {e}")
    if c2.button("🔄 Reiniciar"):
        st.session_state.clear()
        inicializar_estado()
        st.success("Partida reiniciada.")
        st.rerun()
    if c3.button("↩️ Deshacer") and board.move_stack:
        undone = board.pop()
        st.session_state.history.append(f"Deshacer: {undone.uci()}")
        st.session_state.sel_from = None
        st.rerun()

    # --- PGN ---
    st.markdown("### PGN")
    cpg1, cpg2 = st.columns(2)
    with cpg1:
        game = chess.pgn.Game.from_board(board)
        pgn_str = str(game)
        st.download_button("💾 Descargar PGN", data=pgn_str, file_name="partida.pgn", mime="application/x-chess-pgn")
    with cpg2:
        pgn_in = st.text_area("Pega PGN para cargar", value="", height=120, placeholder="[Pega aquí y pulsa Cargar]")
        if st.button("📥 Cargar PGN"):
            try:
                game_in = chess.pgn.read_game(io.StringIO(pgn_in))
                new_board = game_in.board()
                for mv in game_in.mainline_moves():
                    new_board.push(mv)
                st.session_state.board = new_board
                st.session_state.history = []
                st.session_state.sel_from = None
                st.success("PGN cargado.")
                st.rerun()
            except Exception as e:
                st.error(f"PGN inválido: {e}")

with col2:
    prov_txt = st.session_state.provider.upper()
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
                            "OpenAI" if st.session_state.provider=="openai" else ("Gemma" if st.session_state.provider=="gemma" else "Ollama")
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
                    "OpenAI" if st.session_state.provider=="openai" else ("Gemma" if st.session_state.provider=="gemma" else "Ollama")
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
