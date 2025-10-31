import io
import re
import unicodedata
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(
    page_title="Bet365 Extractor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------- UI HEADER ----------------------
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.5rem;}
    .stDownloadButton > button {border-radius: 12px; padding: 0.6rem 1rem; font-weight: 600;}
    .st-emotion-cache-1kyxreq {gap: 0.5rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📊 Bet365 HTML → Excel/CSV")
st.caption("Incolla o carica l’HTML. Estrae **Giocatore, Linea, Quota**. Supporto per Over/Under e layout a colonne.")

# ---------------------- HELPERS ----------------------
def _norm_text(s: str) -> str:
    if s is None:
        return ""
    s = " ".join(s.split())
    return s.strip()

def _contains_over(label: str) -> bool:
    lab = label.lower()
    lab_noaccent = unicodedata.normalize("NFKD", lab).encode("ascii", "ignore").decode("ascii")
    return ("piu di" in lab_noaccent) or ("over" in lab_noaccent)

def _contains_under(label: str) -> bool:
    lab = label.lower()
    lab_noaccent = unicodedata.normalize("NFKD", lab).encode("ascii", "ignore").decode("ascii")
    return ("meno di" in lab_noaccent) or ("under" in lab_noaccent)

def _to_float_odds(x: str):
    if x is None:
        return None
    x = x.strip().replace(",", ".")
    try:
        return float(x)
    except:
        m = re.search(r"\d+[.,]\d+", x)
        if m:
            try:
                return float(m.group(0).replace(",", "."))
            except:
                return None
        return None

def parse_over_under_layout(soup: BeautifulSoup, market_filter: str):
    rows = []
    pods = soup.select(".gl-MarketGroupPod.src-FixtureSubGroup")
    if not pods:
        return rows

    for pod in pods:
        fix_el = pod.select_one(".src-FixtureSubGroupButton_Text")
        fixture = _norm_text(fix_el.get_text()) if fix_el else ""

        players = [_norm_text(e.get_text()) for e in pod.select(".srb-ParticipantLabelWithTeam_Name")]

        for market in pod.select(".gl-Market.gl-Market_General-columnheader"):
            header_el = market.select_one(".gl-MarketColumnHeader")
            market_name = _norm_text(header_el.get_text() if header_el else "")

            if market_filter == "over" and not _contains_over(market_name):
                continue
            if market_filter == "under" and not _contains_under(market_name):
                continue
            # both: no filter

            parts = market.select(".gl-ParticipantCenteredStacked.gl-Participant_General")
            entries = []
            for p in parts:
                line_el = p.select_one(".gl-ParticipantCenteredStacked_Handicap")
                odds_el = p.select_one(".gl-ParticipantCenteredStacked_Odds")
                line = _norm_text(line_el.get_text()) if line_el else ""
                odds = _norm_text(odds_el.get_text()) if odds_el else ""
                entries.append((line, _to_float_odds(odds)))

            n = min(len(players), len(entries))
            for i in range(n):
                line, odds = entries[i]
                rows.append({
                    "Fixture": fixture,
                    "Player": players[i],
                    "Market": market_name,
                    "Line": line,
                    "Odds": odds
                })

    return rows

def parse_columns_layout(soup: BeautifulSoup):
    # layout con intestazioni "0, 5, 10, ..." e quote in ogni colonna
    rows = []

    fixture_el = soup.select_one(".src-FixtureSubGroupButton_Text")
    fixture = _norm_text(fixture_el.get_text()) if fixture_el else ""

    players = [_norm_text(e.get_text()) for e in soup.select(".srb-ParticipantLabelWithTeam_Name")]
    if not players:
        return rows

    columns = soup.select(".srb-HScrollPlaceColumnMarket")
    if not columns:
        return rows

    for col in columns:
        header_el = col.select_one(".srb-HScrollPlaceHeader")
        header = _norm_text(header_el.get_text()) if header_el else ""

        odds_spans = col.select(".gl-ParticipantOddsOnly_Odds")
        odds = [_to_float_odds(_norm_text(sp.get_text())) for sp in odds_spans]

        n = min(len(players), len(odds))
        for i in range(n):
            rows.append({
                "Fixture": fixture,
                "Player": players[i],
                "Market": header,  # header della colonna
                "Line": header,
                "Odds": odds[i],
            })

    return rows

def extract(html: str, market_filter: str = "over") -> pd.DataFrame:
    soup = BeautifulSoup(html, "lxml")

    # 1) tenta layout Over/Under
    rows = parse_over_under_layout(soup, market_filter=market_filter)
    # 2) in fallback, layout a colonne
    if not rows:
        rows = parse_columns_layout(soup)

    df = pd.DataFrame(rows, columns=["Fixture", "Player", "Market", "Line", "Odds"])
    return df

def to_excel_bytes(df: pd.DataFrame) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="estratto")
    bio.seek(0)
    return bio.read()

# ---------------------- SIDEBAR ----------------------
st.sidebar.header("⚙️ Opzioni")
market_opt = st.sidebar.selectbox(
    "Mercato da estrarre",
    options=[("Più di", "over"), ("Meno di", "under"), ("Entrambi", "both")],
    index=0,
    format_func=lambda x: x[0]
)[1]

deduplicate = st.sidebar.checkbox("Rimuovi duplicati (per giocatore+linea)", value=(market_opt != "both"))
st.sidebar.caption("Suggerito ON quando scegli Più di o Meno di.")

# ---------------------- INPUT AREA ----------------------
tab_file, tab_paste = st.tabs(["📁 Carica file HTML/TXT", "📋 Incolla HTML"])

html_content = ""

with tab_file:
    up = st.file_uploader("Carica un file .html / .txt esportato da Bet365", type=["html", "htm", "txt"])
    if up is not None:
        html_content = up.read().decode("utf-8", errors="ignore")

with tab_paste:
    txt = st.text_area("Incolla qui il codice HTML", height=300, placeholder="<!doctype html> ...")
    if txt.strip():
        html_content = txt

run = st.button("🔎 Estrai dati", type="primary", use_container_width=True)

# ---------------------- PROCESS ----------------------
if run:
    if not html_content.strip():
        st.warning("Inserisci o carica l'HTML prima di procedere.")
        st.stop()

    with st.spinner("Estrazione in corso..."):
        df = extract(html_content, market_filter=market_opt)

        if df.empty:
            st.error("Nessun dato riconosciuto. Verifica di aver incollato l’HTML corretto.")
            st.stop()

        if deduplicate:
            df = df.drop_duplicates(subset=["Fixture", "Player", "Line", "Odds"]).reset_index(drop=True)

    st.success(f"✅ Righe estratte: {len(df)}")

    # Preview
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Download buttons
    col1, col2 = st.columns(2)
    with col1:
        csv_bytes = df.to_csv(index=False, encoding="utf-8").encode("utf-8")
        st.download_button(
            "⬇️ Scarica CSV",
            data=csv_bytes,
            file_name="bet365_estratto.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with col2:
        xlsx_bytes = to_excel_bytes(df)
        st.download_button(
            "⬇️ Scarica Excel",
            data=xlsx_bytes,
            file_name="bet365_estratto.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

# Footer
st.caption("Tip: per evitare duplicati, usa il filtro “Più di” o “Meno di”. Con “Entrambi” è normale avere due righe per giocatore.")
