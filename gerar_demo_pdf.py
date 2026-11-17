# Gera demonstracao.pdf (1 página) a partir da simulação em index.html,
# e a imagem demonstracao.png (é ela que vai anexada na 2ª etapa).
#   python gerar_demo_pdf.py                  # sobrescreve os arquivos do projeto
#   python gerar_demo_pdf.py --saida X.pdf    # gera em outro lugar (para conferir)
import argparse
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

BASE = Path(__file__).resolve().parent
HTML = BASE / "index.html"
SAIDA = BASE / "demonstracao.pdf"

AZUL = colors.HexColor("#123a6b")
AZUL_ESC = colors.HexColor("#07162c")
AZUL_CLARO = colors.HexColor("#eaf1fa")
DOURADO = colors.HexColor("#d4af63")
DOURADO_SUAVE = colors.HexColor("#fbf7ee")
VERDE = colors.HexColor("#128c7e")
VERDE_CLARO = colors.HexColor("#e9f6ef")
VERMELHO_CLARO = colors.HexColor("#fbeeed")
VERMELHO = colors.HexColor("#b4453c")
CINZA = colors.HexColor("#5b6470")
BORDA = colors.HexColor("#d9dee6")
TEXTO = colors.HexColor("#1d2733")

W, H = A4
M = 14 * mm


def capturar_celular() -> Path:
    destino = Path(tempfile.gettempdir()) / "demo_celular.png"
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page(viewport={"width": 1280, "height": 900})
        pagina.goto(HTML.resolve().as_uri())
        # A animação do chat só começa quando #conversa entra na tela
        # (IntersectionObserver); sem este scroll o celular ficava vazio.
        pagina.locator("#conversa").scroll_into_view_if_needed()
        # Espera determinística: #painelResumo ganha "completo" no fim da animação.
        pagina.wait_for_selector("#painelResumo.completo", timeout=45000)
        pagina.evaluate("document.getElementById('conversa').scrollTop = 0")
        pagina.wait_for_timeout(300)
        pagina.locator(".celular").screenshot(path=str(destino))
        navegador.close()
    return destino


def par(txt: str, size: float = 8.4, cor=TEXTO, bold: bool = False,
        leading: float | None = None, align: int = 0) -> Paragraph:
    estilo = ParagraphStyle(
        "p", fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size, textColor=cor, leading=leading or size * 1.35,
        alignment=align, spaceAfter=0, spaceBefore=0,
    )
    return Paragraph(txt, estilo)


def lado_a_lado(esquerda: list, direita: list, largura: float, vao: float,
                estilo_esq: list, estilo_dir: list) -> Table:
    """Duas caixas na mesma linha, com a MESMA altura e ocupando `largura` inteira.

    Uma tabela só (coluna do meio vazia = vão): as caixas ficam alinhadas no
    topo e na base, e a borda direita bate com a margem da página.
    """
    col = (largura - vao) / 2

    def empilhar(itens: list) -> list:
        # Uma célula por caixa: cada lado mantém o próprio espaçamento entre
        # itens (linhas compartilhadas abriam buracos no lado mais curto).
        pilha = []
        for i, item in enumerate(itens):
            if i:
                pilha.append(Spacer(1, 4.2))
            pilha.append(item)
        return pilha

    t = Table([[empilhar(esquerda), "", empilhar(direita)]], colWidths=[col, vao, col])
    comandos = [("LEFTPADDING", (1, 0), (1, -1), 0), ("RIGHTPADDING", (1, 0), (1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP")]
    for coluna, estilo in ((0, estilo_esq), (2, estilo_dir)):
        for cmd, *args in estilo:
            comandos.append((cmd, (coluna, 0), (coluna, -1), *args))
    t.setStyle(TableStyle(comandos))
    return t


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path, default=SAIDA,
                        help="PDF de saída (a imagem .png é gerada ao lado)")
    saida = parser.parse_args().saida.resolve()

    img = capturar_celular()

    c = canvas.Canvas(str(saida), pagesize=A4)
    c.setTitle("Automações para Clínicas — Demonstração")
    c.setAuthor("Nickolas")

    # ---------------- cabeçalho ----------------
    cab_h = 27 * mm
    c.setFillColor(AZUL_ESC)
    c.rect(0, H - cab_h, W, cab_h, stroke=0, fill=1)
    c.setFillColor(DOURADO)
    c.rect(0, H - cab_h, W, 1.2 * mm, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 7.4)
    c.drawCentredString(W / 2, H - 6.2 * mm, "AUTOMAÇÕES PARA CLÍNICAS")
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 17)
    c.drawCentredString(W / 2, H - 13 * mm, "Atendimento Inteligente & Gestão Fiscal")
    c.setFont("Helvetica", 8.8)
    c.drawCentredString(
        W / 2, H - 18.2 * mm,
        "Demonstração — triagem de pacientes pelo WhatsApp e emissão automática de NFS-e")
    c.setFillColor(colors.HexColor("#a9bddb"))
    c.setFont("Helvetica", 7.5)
    c.drawCentredString(
        W / 2, H - 23 * mm,
        "Exemplo ilustrativo · solução já em funcionamento em uma clínica médica da região")

    y = H - cab_h - 7 * mm

    # ---------------- etapa 1: triagem ----------------
    c.setFillColor(DOURADO)
    c.setFont("Helvetica-Bold", 10.2)
    c.drawString(M, y, "01 ·")
    c.setFillColor(AZUL_ESC)
    c.drawString(M + 8 * mm, y, "TRIAGEM PELO WHATSAPP")
    c.setStrokeColor(BORDA)
    c.setLineWidth(0.6)
    c.line(M + 58 * mm, y + 1.2 * mm, W - M, y + 1.2 * mm)
    y -= 4.6 * mm
    p_intro = par(
        "O paciente conversa normalmente; ao final, a recepção recebe a queixa "
        "já resumida e organizada — sem repetir as mesmas perguntas.")
    _, h_intro = p_intro.wrapOn(c, W - 2 * M, H)
    p_intro.drawOn(c, M, y - h_intro)
    y -= h_intro + 4 * mm

    # coluna esquerda: print do celular
    img_w = 52 * mm
    ir = ImageReader(str(img))
    iw, ih = ir.getSize()
    img_h = img_w * ih / iw
    c.drawImage(ir, M, y - img_h, width=img_w, height=img_h, mask="auto")

    # coluna direita: cartão de resumo
    x_dir = M + img_w + 6 * mm
    larg_dir = W - M - x_dir

    resumo = [
        [par("TRIAGEM ORGANIZADA — o que a recepção recebe", 8.6, VERDE, True)],
        [par("<b>Paciente:</b> Mariana Costa", 8.4)],
        [par("<b>Motivo:</b> dor aguda — molar inferior direito", 8.4)],
        [par("<b>Histórico:</b> há 3 dias; analgésico sem alívio", 8.4)],
        [par("<b>Convênio:</b> particular", 8.4)],
        [par("<b>Preferência:</b> tarde — quinta-feira", 8.4)],
        [par("<b>Próxima ação:</b> recepção confirma o encaixe e o paciente "
             "chega com os dados já registrados.", 8.4)],
    ]
    t_resumo = Table(resumo, colWidths=[larg_dir])
    t_resumo.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), VERDE_CLARO),
        ("LINEBEFORE", (0, 0), (0, -1), 3, VERDE),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDA),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 3.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    _, h_res = t_resumo.wrapOn(c, larg_dir, H)
    ty = y - h_res
    t_resumo.drawOn(c, x_dir, ty)

    # antes / depois
    ty -= 4 * mm
    antes = [
        par("HOJE", 8.2, VERMELHO, True),
        par("• mensagens espalhadas ao longo do dia", 7.9),
        par("• mesmas perguntas repetidas a cada contato", 7.9),
        par("• informação importante se perde na conversa", 7.9),
    ]
    depois = [
        par("COM A TRIAGEM", 8.2, VERDE, True),
        par("• conversa conduzida em um único contato", 7.9),
        par("• queixa e dados já resumidos", 7.9),
        par("• recepção recebe tudo organizado", 7.9),
    ]
    def caixa(fundo):
        return [("BACKGROUND", fundo), ("BOX", 0.6, BORDA), ("LEFTPADDING", 6),
                ("RIGHTPADDING", 5), ("TOPPADDING", 2.6), ("BOTTOMPADDING", 2.6)]

    t_comp = lado_a_lado(antes, depois, larg_dir, 3 * mm,
                         caixa(VERMELHO_CLARO), caixa(VERDE_CLARO))
    _, h_comp = t_comp.wrapOn(c, larg_dir, H)
    t_comp.drawOn(c, x_dir, ty - h_comp)
    y = min(ty - h_comp, y - img_h) - 11 * mm

    # ---------------- etapa 2: NFS-e ----------------
    c.setFillColor(DOURADO)
    c.setFont("Helvetica-Bold", 10.2)
    c.drawString(M, y, "02 ·")
    c.setFillColor(AZUL_ESC)
    c.drawString(M + 8 * mm, y, "EMISSÃO DE NFS-E E PÓS-ATENDIMENTO")
    c.setStrokeColor(BORDA)
    c.setLineWidth(0.6)
    c.line(M + 85 * mm, y + 1.2 * mm, W - M, y + 1.2 * mm)
    y -= 4.6 * mm
    p2 = par(
        "Os dados do atendimento já estão capturados: a nota deixa de ser manual "
        "e é concluída em poucos minutos, com validação em um clique.")
    _, h2 = p2.wrapOn(c, W - 2 * M, H)
    p2.drawOn(c, M, y - h2)
    y -= h2 + 5 * mm

    manual = [
        par("PROCESSO MANUAL — COMO FUNCIONA HOJE", 8.2, CINZA, True),
        par("<b>1.</b> atendimento concluído, dados anotados ou repassados", 7.9),
        par("<b>2.</b> digitação no sistema, campo a campo", 7.9),
        par("<b>3.</b> conferência manual para evitar erro", 7.9),
        par("<b>4.</b> validação repetida para cada nota", 7.9),
        par("vários minutos por nota, com risco de erro", 7.9, VERMELHO, True),
    ]
    auto = [
        par("COM AUTOMAÇÃO — COMO PASSARIA A FUNCIONAR", 8.2, AZUL, True),
        par("<b>1.</b> dados já capturados na triagem", 7.9),
        par("<b>2.</b> nota gerada em poucos minutos", 7.9),
        par("<b>3.</b> equipe confere e valida em 1 clique", 7.9),
        par("<b>4.</b> NFS-e enviada ao paciente no WhatsApp", 7.9),
        par("poucos minutos · validação em um clique", 7.9, AZUL, True),
    ]
    estilo_manual = [("BACKGROUND", colors.HexColor("#f4f5f7")), ("BOX", 0.6, BORDA),
                     ("LEFTPADDING", 6), ("RIGHTPADDING", 5),
                     ("TOPPADDING", 2.8), ("BOTTOMPADDING", 2.8)]
    estilo_auto = [("BACKGROUND", AZUL_CLARO), ("BOX", 0.6, BORDA),
                   ("LINEBEFORE", 3, AZUL), ("LEFTPADDING", 7), ("RIGHTPADDING", 5),
                   ("TOPPADDING", 2.8), ("BOTTOMPADDING", 2.8)]
    t_nfse = lado_a_lado(manual, auto, W - 2 * M, 5 * mm, estilo_manual, estilo_auto)
    _, h_nfse = t_nfse.wrapOn(c, W - 2 * M, H)
    t_nfse.drawOn(c, M, y - h_nfse)
    y -= h_nfse + 11 * mm

    # ---------------- como funciona ----------------
    c.setFillColor(DOURADO)
    c.setFont("Helvetica-Bold", 10.2)
    c.drawString(M, y, "03 ·")
    c.setFillColor(AZUL_ESC)
    c.drawString(M + 8 * mm, y, "IMPLANTAÇÃO SEM ATRITO")
    c.setStrokeColor(BORDA)
    c.setLineWidth(0.6)
    c.line(M + 61 * mm, y + 1.2 * mm, W - M, y + 1.2 * mm)
    y -= 5 * mm
    passos = [
        par("<b>1. Demonstração</b><br/>conversa objetiva, online ou "
            "presencial (12h–13h, após 17h seg–qui ou 16h sex)", 8),
        par("<b>2. Implantação</b><br/>configuração da triagem e da NFS-e "
            "conforme a rotina da clínica", 8),
        par("<b>3. Uso diário</b><br/>conversas organizadas na recepção e "
            "notas validadas em um clique", 8),
    ]
    t_passos = Table([[p for p in passos]],
                     colWidths=[(W - 2 * M) / 3] * 3)
    t_passos.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDA),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    _, h_p = t_passos.wrapOn(c, W - 2 * M, H)
    t_passos.drawOn(c, M, y - h_p)
    y -= h_p + 12 * mm

    # ---------------- CTA ----------------
    cta_h = 34 * mm
    c.setFillColor(AZUL_ESC)
    c.rect(M, y - cta_h, W - 2 * M, cta_h, stroke=0, fill=1)
    c.setFillColor(DOURADO)
    c.rect(M, y - 1.2 * mm, W - 2 * M, 1.2 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(W / 2, y - 9 * mm, "Quer ver funcionando na sua clínica?")
    c.setFont("Helvetica", 8.6)
    c.drawCentredString(
        W / 2, y - 15 * mm,
        "Posso apresentar o funcionamento em uma conversa breve e objetiva,")
    c.drawCentredString(
        W / 2, y - 19.2 * mm,
        "sem compromisso (horários: 12h–13h, após 17h seg–qui ou após 16h sex).")
    c.setFillColor(colors.HexColor("#25d366"))
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(W / 2, y - 25.5 * mm,
                        "Agende pelo WhatsApp: (79) 98167-7954")
    c.setFillColor(colors.HexColor("#9fb4d4"))
    c.setFont("Helvetica", 7.6)
    c.drawCentredString(W / 2, y - 30.5 * mm, "wa.me/5579981677954")
    y -= cta_h
    if y < 14 * mm:  # o rodapé fica em 8 mm: texto a mais invadiria o rodapé
        raise SystemExit(f"ERRO: o conteúdo passou do fim da página ({y / mm:.1f} mm). "
                         "Encurte os textos antes de gerar.")

    # ---------------- rodapé ----------------
    c.setFillColor(CINZA)
    c.setFont("Helvetica", 7)
    c.drawCentredString(
        W / 2, 8 * mm,
        "Demonstração ilustrativa · Automações para clínicas · "
        "Triagem pelo WhatsApp e emissão de NFS-e")

    c.showPage()
    c.save()
    print(f"PDF gerado: {saida}")

    import shutil
    import subprocess
    if shutil.which("pdftoppm"):
        png_base = saida.with_suffix("")
        subprocess.run(
            ["pdftoppm", "-png", "-r", "180", "-singlefile", str(saida), str(png_base)],
            check=True,
        )
        print(f"Imagem gerada: {png_base}.png")
    else:
        # Sem o pdftoppm (Poppler), usa o PyMuPDF se estiver instalado.
        try:
            import pymupdf
        except ImportError:
            print("AVISO: demonstracao.png NÃO foi atualizada "
                  "(instale o Poppler ou 'pip install pymupdf').")
        else:
            with pymupdf.open(str(saida)) as doc:
                doc[0].get_pixmap(dpi=180).save(str(saida.with_suffix(".png")))
            print(f"Imagem gerada: {saida.with_suffix('.png')}")


if __name__ == "__main__":
    main()
