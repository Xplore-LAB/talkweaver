"""Reusable PDF text primitives; no report-specific input or output paths."""
import os, html
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

pdfmetrics.registerFont(TTFont('ReaderCJK',os.environ.get('TALKWEAVER_CJK_FONT','/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf')))
pdfmetrics.registerFont(TTFont('ReaderLatin',os.environ.get('TALKWEAVER_LATIN_FONT','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')))
styles={
 'title':ParagraphStyle('title',fontName='ReaderCJK',fontSize=19,leading=29,spaceAfter=14),
 'heading':ParagraphStyle('heading',fontName='ReaderCJK',fontSize=14,leading=22,spaceAfter=9,keepWithNext=True),
 'body':ParagraphStyle('body',fontName='ReaderCJK',fontSize=10.5,leading=17,spaceAfter=8,wordWrap='CJK'),
 'small':ParagraphStyle('small',fontName='ReaderCJK',fontSize=8.5,leading=13,textColor='#566576',spaceAfter=6,wordWrap='CJK'),
}
def p(t,style='body'):
 # Droid's fallback font omits Latin letters and numerals: select a real glyph
 # per run instead of silently printing blanks for timestamps and acronyms.
 chars=pdfmetrics.getFont('ReaderCJK').face.charWidths
 runs=[];font=None;buf=''
 for ch in str(t):
  use='ReaderCJK' if ord(ch)>127 and ord(ch) in chars else 'ReaderLatin'
  if use!=font and buf:runs.append((font,buf));buf=''
  font=use;buf+=ch
 if buf:runs.append((font,buf))
 markup=''.join('<font name="'+f+'">'+html.escape(s).replace('\n','<br/>')+'</font>' for f,s in runs)
 return Paragraph(markup,styles[style])
