"""Independent optional developer check: openpyxl + LibreOffice, no runtime dependencies.
Checks formula caches in exported books against a real spreadsheet recalculation.
"""
import io,json,math,subprocess,tempfile,sys
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import xml.etree.ElementTree as ET
import openpyxl
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from albion_trade_desk import refining

def recalc(path,directory,profile):
    subprocess.run(['soffice','-env:UserInstallation='+profile.as_uri(),'--headless','--convert-to','xlsx','--outdir',str(directory),str(path)],check=True,capture_output=True,timeout=60)
    return directory/path.name

def cache_template():
    path=refining.TEMPLATES/'cloth_calculator.xlsx';ns='{'+refining.NS+'}'
    with tempfile.TemporaryDirectory(prefix='albion-cloth-cache-') as td:
        temp=Path(td);out=temp/'recalc';out.mkdir();cached=openpyxl.load_workbook(recalc(path,out,temp/'profile'),data_only=True)
        stream=io.BytesIO()
        with ZipFile(path) as src,ZipFile(stream,'w',ZIP_DEFLATED) as dst:
            for member in src.infolist():
                content=src.read(member.filename)
                if member.filename.startswith('xl/worksheets/sheet') and member.filename.endswith('.xml'):
                    index=int(member.filename.rsplit('sheet',1)[1].split('.')[0])-1;root=ET.fromstring(content)
                    for cell in root.iter(ns+'c'):
                        if cell.find(ns+'f') is None:continue
                        value=cached.worksheets[index][cell.attrib['r']].value
                        if isinstance(value,str) and value.startswith('#'):raise AssertionError((index,cell.attrib['r'],value))
                        old=cell.find(ns+'v')
                        if old is not None:cell.remove(old)
                        if value is not None:
                            if isinstance(value,str):cell.set('t','str')
                            ET.SubElement(cell,ns+'v').text=str(value)
                    content=ET.tostring(root,encoding='utf-8',xml_declaration=True)
                dst.writestr(member,content)
        path.write_bytes(stream.getvalue())

if '--cache-template' in sys.argv:cache_template()
scenarios=[{}, {'batch':77,'return_rate':50,'tax_pct':6.5,'station':8,'steps':7,'levels':{'4':20,'5':50,'6':10,'7':81,'8':74}},
    {'batch':77,'return_rate':53.9,'steps':5,'rounding':'integer'}, {'batch':1,'return_rate':0,'steps':0}]
report={'cases':[],'mismatches':[]}
with tempfile.TemporaryDirectory(prefix='albion-cloth-validate-') as td:
    temp=Path(td);out=temp/'recalc';out.mkdir()
    for i,cfg in enumerate(scenarios):
        path=temp/f'case-{i}.xlsx';path.write_bytes(refining.workbook(cfg));cached=openpyxl.load_workbook(path,data_only=True);formulas=openpyxl.load_workbook(path,data_only=False)
        checked=openpyxl.load_workbook(recalc(path,out,temp/'profile'),data_only=True);count=0
        for sheet in formulas:
            if sheet.title in ('Проверка','Исходная таблица'):continue
            for row in sheet:
                for cell in row:
                    if cell.data_type!='f':continue
                    count+=1;a=cached[sheet.title][cell.coordinate].value;b=checked[sheet.title][cell.coordinate].value
                    same=math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-6) if isinstance(a,(float,int)) and isinstance(b,(float,int)) else a==b or {a,b}=={None,''}
                    if not same:report['mismatches'].append([i,sheet.title,cell.coordinate,a,b])
        report['cases'].append({'config':cfg,'formulas_compared':count})
print(json.dumps(report,ensure_ascii=False,indent=2))
if report['mismatches']:raise SystemExit(1)
