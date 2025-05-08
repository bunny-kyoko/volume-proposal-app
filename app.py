import streamlit as st
from openai import OpenAI
from fpdf import FPDF
import pandas as pd
import io
import datetime
import re
import os
from dotenv import load_dotenv

# 環境変数からAPIキーを読み込む
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

# 用途地域ルール
zone_rules = {
    "第一種低層住居専用地域": "建ぺい率30〜60%、容積率50〜100%、高さ制限10mまたは12m、日影規制あり、住居専用",
    "第二種低層住居専用地域": "第一種と同様だが、小規模店舗・事務所も可",
    "第一種中高層住居専用地域": "住居を中心、共同住宅可、学校・病院なども可、日影制限あり",
    "第二種中高層住居専用地域": "第一種よりやや用途が広く、店舗もある程度可",
    "第一種住居地域": "住居中心、大規模店舗は不可",
    "第二種住居地域": "第一種より広範、ホテル・カラオケ等も可",
    "準住居地域": "幹線道路沿いの用途混在可、商業・住宅併用可",
    "近隣商業地域": "小規模商業＋住居可、騒音規制あり",
    "商業地域": "商業中心、住宅・共同住宅可、高容積率、防火地域あり",
    "準工業地域": "工場・住宅・商業混在可、環境悪化施設不可",
    "工業地域": "住宅も建築可、用途制限あり、規模の大きな施設可",
    "工業専用地域": "住宅建築不可、工場専用、高容積率",
    "用途地域外（白地）": "用途制限なし（都市計画区域外）"
}

zone_structure_rules = {
    "第一種低層住居専用地域": ["木造", "RC造（鉄筋コンクリート造）"],
    "第二種低層住居専用地域": ["木造", "RC造（鉄筋コンクリート造）"],
    "第一種中高層住居専用地域": ["木造", "RC造（鉄筋コンクリート造）", "S造（鉄骨造）"],
    "第二種中高層住居専用地域": ["木造", "RC造（鉄筋コンクリート造）", "S造（鉄骨造）"],
    "第一種住居地域": ["木造", "RC造（鉄筋コンクリート造）", "S造（鉄骨造）"],
    "第二種住居地域": ["木造", "RC造（鉄筋コンクリート造）", "S造（鉄骨造）"],
    "準住居地域": ["木造", "RC造（鉄筋コンクリート造）", "S造（鉄骨造）"],
    "近隣商業地域": ["木造", "RC造（鉄筋コンクリート造）", "S造（鉄骨造）"],
    "商業地域": ["木造", "RC造（鉄筋コンクリート造）", "S造（鉄骨造）"],
    "準工業地域": ["RC造（鉄筋コンクリート造）", "S造（鉄骨造）"],
    "工業地域": ["RC造（鉄筋コンクリート造）", "S造（鉄骨造）"],
    "工業専用地域": ["RC造（鉄筋コンクリート造）", "S造（鉄骨造）"],
    "用途地域外（白地）": ["木造", "RC造（鉄筋コンクリート造）", "S造（鉄骨造）"]
}

unit_prices = {
    "木造": 350000,
    "RC造（鉄筋コンクリート造）": 500000,
    "S造（鉄骨造）": 400000
}

# PDF生成関数
def generate_pdf(proposals, table_df):
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("IPA", "", "ipaexg.ttf", uni=True)
    pdf.set_font("IPA", size=12)

    pdf.cell(0, 10, "建築提案書", ln=True)
    pdf.set_font("IPA", size=10)
    pdf.cell(0, 10, f"作成日：{datetime.date.today()}", ln=True)
    pdf.ln(10)

    pdf.set_font("IPA", size=11)
    pdf.cell(0, 10, "【構造別 概算費用 比較表】", ln=True)
    for i, row in table_df.iterrows():
        pdf.cell(0, 8, f"{row['構造']}: 延床 {row['延床面積']}㎡ / 単価 {row['単価']} 円 → 概算費用 {row['概算費用']:,} 円", ln=True)
    pdf.ln(5)

    for item in proposals:
        pdf.set_font("IPA", size=11)
        pdf.cell(0, 10, f"【{item['構造']} の提案】", ln=True)
        pdf.set_font("IPA", size=10)
        for line in item["提案"].split("\n"):
            pdf.multi_cell(0, 6, line)
        pdf.ln(4)

    return pdf.output(dest="S").encode("latin1")

# Streamlit アプリ本体
st.set_page_config(page_title="建築提案＋構造判定", layout="centered")
st.title("構造別 建築提案書（用途地域・構造制限対応）")

with st.form("input_form"):
    st.subheader("【敷地条件の入力】")
    col1, col2 = st.columns(2)
    with col1:
        site_area = st.number_input("敷地面積（㎡）", value=150)
        bpr = st.number_input("建ぺい率（%）", value=60)
        road_width = st.number_input("前面道路幅員（m）", value=4.0)
    with col2:
        far = st.number_input("容積率（%）", value=200)
        usage = st.text_input("建物用途", "住宅")
        fire_zone = st.selectbox("防火指定", ["なし", "準防火地域", "防火地域"])

    zone = st.selectbox("用途地域", list(zone_rules.keys()))
    st.markdown(f"🧾 **用途地域の概要**：{zone_rules[zone]}")

    structures = st.multiselect(
        "比較する構造（複数選択可）",
        ["木造", "RC造（鉄筋コンクリート造）", "S造（鉄骨造）"],
        default=["木造", "RC造（鉄筋コンクリート造）"]
    )

    allowed_structures = zone_structure_rules.get(zone, [])
    disallowed = [s for s in structures if s not in allowed_structures]

    if disallowed:
        st.warning(f"⚠️ 以下の構造は「{zone}」では建築が制限される可能性があります: {', '.join(disallowed)}")

    submit = st.form_submit_button("▶ 提案を生成")

if submit:
    filtered_structures = [s for s in structures if s in allowed_structures]
    if not filtered_structures:
        st.error("有効な構造がありません。用途地域と構造の組み合わせを確認してください。")
        st.stop()

    st.info("GPTによる構造別提案を生成中…")
    proposal_data = []
    selected_rule = zone_rules.get(zone, "用途地域の補足は未定義です。")

    for struct in filtered_structures:
        prompt = f"""
あなたは建築士です。
以下の敷地条件に基づき、「{struct}」構造で建てる場合の提案を出してください：

- 用途地域：{zone}
- 敷地面積：{site_area}㎡、建ぺい率：{bpr}%、容積率：{far}%
- 前面道路幅員：{road_width}m、防火指定：{fire_zone}
- 用途：{usage}

【用途地域に関する補足】
{selected_rule}

以下を含めてください：
1. 建築可能階数
2. 延床面積（概算、㎡）
3. 構造の特徴・用途例・法的注意点
4. 説明文章
"""

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "あなたは建築法規に詳しい一級建築士です。"},
                {"role": "user", "content": prompt}
            ]
        )

        content = response.choices[0].message.content.strip()
        match = re.search(r"延床面積.*?([0-9]+)\s*㎡", content)
        area = int(match.group(1)) if match else int(site_area * far / 100)
        price = unit_prices[struct]
        cost = area * price

        proposal_data.append({
            "構造": struct,
            "延床面積": area,
            "単価": price,
            "概算費用": cost,
            "提案": content
        })

        st.subheader(f"【{struct}】の提案")
        st.markdown(content)
        st.markdown(f"📐 **延床面積（推定）**: {area}㎡")
        st.markdown(f"💰 **概算建設費**: {cost:,} 円")
        st.divider()

    df = pd.DataFrame(proposal_data)[["構造", "延床面積", "単価", "概算費用"]]
    st.subheader("構造別 概算費用 比較表")
    st.table(df)

    pdf_output = generate_pdf(proposal_data, df)

    st.subheader("📄 提案書PDFを出力")
    st.download_button(
        label="提案書をPDFでダウンロード",
        data=pdf_output,
        file_name="建築提案書.pdf",
        mime="application/pdf"
    )
