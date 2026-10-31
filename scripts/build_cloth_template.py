"""Developer tool: preserve the uploaded workbook and add transparent calculation sheets.
Usage: python scripts/build_cloth_template.py /path/to/original.xlsx
Requires openpyxl only for regenerating the template, never for running the app.
"""
from pathlib import Path
import hashlib,json,sys
import openpyxl
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.workbook.properties import CalcProperties

source=Path(sys.argv[1]);root=Path(__file__).resolve().parents[1]/'albion_trade_desk'/'templates'
w=openpyxl.load_workbook(source);old=w.active;old.title='Исходная таблица'
rows=[]
for t in range(4,9):
 for e in range(5):
  r=8+(t-4)*6+e
  rows.append(dict(tier=t,enchantment=e,fiber=old[f'F{r}'].value,cloth_buy=old[f'Y{r}'].value,sale=old[f'W{r}'].value,legacy_focus=old[f'AB{r}'].value))
settings=dict(batch=100,return_rate=53.9,tax_pct=0,station=0,t3_price=old['C6'].value,coefficient=old['R2'].value,mode='finite',rounding='continuous',steps=5,
 secondary_initial=88,secondary_rate=10,levels={str(t):old[f'L{t+36}'].value for t in range(4,9)},rows=rows)
(root/'cloth_defaults.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
p=w.create_sheet('Параметры',0);c=w.create_sheet('Ткань',1);l=w.create_sheet('Возврат',2);audit=w.create_sheet('Проверка',3);calc=w.create_sheet('Повторы',4)
p.append(['Параметр','Значение','Пояснение','Тир','Специализация 0–100'])
labels=[('Начальная партия',100,'Полный расход материалов на начальную партию'),('Возврат, %',53.9,'Сценарное предположение, не автоматический бонус города'),('Дополнительные налоги, %',0,'Ноль по умолчанию: неизвестно, включены ли они в W исходника'),('Станция за операцию',0,'Укажите вручную'),('Цена ткани T3',settings['t3_price'],'Для всех T4, включая зачарованные'),('Добавочные единицы на 100',111,'Только для режима coefficient'),('Режим возврата','finite','finite: ограниченные повторы, coefficient: ручной, percent: теоретический предел'),('Повторных переработок',5,'0–30; начальная партия идёт дополнительно'),('Вторая начальная партия',88,'Отдельный пример исходного файла'),('Второй возврат, %',10,'Отдельный пример исходного файла'),('Округление ресурсов','continuous','integer: каждый возвращённый материал вниз; continuous: без округления')]
for row in labels:p.append(row)
for i,t in enumerate(range(4,9),2):p[f'D{i}']=t;p[f'E{i}']=settings['levels'][str(t)]
p['D7']='Общий FCE';p['E7']='=30*SUM(E2:E6)'
p['A14']='Цены перенесены из исходного Excel. Их рыночная дата неизвестна.'
p['A15']='Focus: модель исходного Excel; базовый расход в каталоге округлён и может отличаться.'
p['A16']='5 повторов после начальной партии; integer — осторожный сценарий, не доказательство игрового округления.'
c.append(['ТКАНЬ — сценарий переработки, не гарантированная прибыль'])
c.append(['Редактируйте персиковые клетки. Цена покупки ткани используется как вход следующего тира.'])
c.append(['Результат до дополнительных расходов, которые не указаны в Параметрах.'])
c.append(['Столбцы P–R: исходный расчёт на 100 + 111 единиц, без налогов и станции.'])
c.append([])
c.append(['Тир','Чары','Волокна/оп.','Покупка волокна','Покупка ткани','Продажа ткани','Ткань предыдущая','Материалы/оп.','Начальные материалы','Ожидаемый выпуск','Focus нач. партии','Выручка после налогов','Станция всего','Оценка прибыли','Серебро/Focus','Focus из Excel','Исходная прибыль','Исходное серебро/Focus'])
P="'Параметры'!"
for i,row in enumerate(rows,7):
 t,e=row['tier'],row['enchantment'];spec=t-2;previous=f'{P}$B$6' if t==4 else f'E{i-5}'
 values=[t,e,min(t-2,5),row['fiber'],row['cloth_buy'],row['sale'],f'={previous}',f'=D{i}*C{i}+G{i}',f'=H{i}*{P}$B$2',
 f"=IF({P}$B$8=\"coefficient\",{P}$B$2*(1+{P}$B$7/100),IF({P}$B$8=\"percent\",{P}$B$2/(1-{P}$B$3/100),'Повторы'!J{33+(i-7)*33}))",
 f'=ROUND(10*POWER(1.75,A{i}+B{i}-1)*{P}$B$2/POWER(2,({P}$E$7+250*{P}$E${spec})/10000),0)',
 f'=J{i}*F{i}*(1-{P}$B$4/100)',f'=J{i}*{P}$B$5',f'=L{i}-I{i}-M{i}',f'=IF(K{i}=0,"",N{i}/(K{i}*J{i}/{P}$B$2))',
 row['legacy_focus'],f'=F{i}*211-H{i}*100',f'=IF(P{i}=0,"",Q{i}/P{i})']
 c.append(values)
calc.append(['Промежуточные остатки каждого материала: округление и ограничение повторов'])
calc.append(['Вариант','Повтор (0=первая партия)','Волокно до','Ткань до','Операции','Вернулось волокна','Вернулось ткани','Остаток волокна','Остаток ткани','Всего продукции','Focus'])
for index,item in enumerate(rows+[None]):
 first=3+index*33;main=7+index;factor=min(item['tier']-2,5) if item else 5
 initial=f'{P}$B$2' if item else f'{P}$B$10';rate=f'{P}$B$3' if item else f'{P}$B$11'
 focus=f"'Ткань'!$K${main if item else 29}/{P}$B$2"
 for n in range(31):
  r=first+n
  vals=[f"T{item['tier']}.{item['enchantment']}" if item else 'Вторая партия',n,
   f'={initial}*{factor}' if n==0 else f'=H{r-1}',f'={initial}' if n==0 else f'=I{r-1}',
   f'=IF(B{r}<={P}$B$9,IF({P}$B$12="integer",ROUNDDOWN(MIN(C{r}/{factor},D{r}),0),MIN(C{r}/{factor},D{r})),0)',
   f'=IF({P}$B$12="integer",ROUNDDOWN(E{r}*{factor}*{rate}/100,0),E{r}*{factor}*{rate}/100)',
   f'=IF({P}$B$12="integer",ROUNDDOWN(E{r}*{rate}/100,0),E{r}*{rate}/100)',
   f'=C{r}-E{r}*{factor}+F{r}',f'=D{r}-E{r}+G{r}',f'=SUM(E{first}:E{r})',f'=E{r}*{focus}']
  for col,v in enumerate(vals,1):calc.cell(r,col,v)
l['A1']='КОНЕЧНЫЕ ПОВТОРЫ — начальная партия + заданное число повторов';l['A2']='Последний остаток не считается готовой тканью. Focus на примере T8.2.'
for start,index in [(5,22),(41,25)]:
 first=3+index*33
 for col,name in enumerate(['Шаг','Обрабатывается','Можно операций из остатка','Всего произведено','Focus (модель T8.2)'],1):l.cell(start-1,col,name)
 for n in range(31):
  r=start+n;at=first+n
  vals=[n+1,f"='Повторы'!E{at}",f"=IF({P}$B$12=\"integer\",ROUNDDOWN(MIN('Повторы'!H{at}/5,'Повторы'!I{at}),0),MIN('Повторы'!H{at}/5,'Повторы'!I{at}))",f"='Повторы'!J{at}",f"='Повторы'!K{at}"]
  for col,v in enumerate(vals,1):l.cell(r,col,v)
 l.cell(start+31,4,'Всего Focus');l.cell(start+31,5,f'=SUM(E{start}:E{start+30})')
notes=[['Проверка исходной таблицы','Результат'],['SHA-256 исходника',hashlib.sha256(source.read_bytes()).hexdigest()],
 ['Формул исходника',250],['Независимый пересчёт LibreOffice','250 формул; ошибок и расхождений с кэшем не найдено'],
 ['Коэффициент 111','Округление вниз суммы первых пяти последовательных возвратов по 53.9%: 111.6007192 на начальные 100.'],
 ['Восстановлена логика 111','53.9% последовательно: 4 возврата дают +107.051427%, 5 дают +111.600719%. Основная модель конечная: 5 повторов.'],
 ['Подпись 57,3','Не соответствует коэффициенту 111. В новой модели процент задан явно.'],
 ['B26','В исходнике Т7.1, тогда как остальные подписи строки обозначают T7.0. Новая таблица использует тир+чары отдельно.'],
 ['Y48','Сумма Y38:Y43 верна для первой партии и пяти повторов: 35079.167225. Новая вкладка меняет длину суммы с числом повторов.'],
 ['AC38:AC47','Суммирует начальную партию и возвраты. Последний возврат ещё не переработан. Новая модель разделяет выпуск и остаток.'],
 ['AB8:AB36','Ручной Focus не связан с матрицей уровней. Сохранён в колонке P для сравнения, новый Focus считается по уровням.'],
 ['Налоги и станция','В исходных формулах отдельного учёта нет. Добавлены явные параметры с нулём по умолчанию.'],
 ['Округление Focus','Сохранена формула исходного Excel. Она не является подтверждением точного игрового округления.'],
 ['Архив','Лист Исходная таблица сохранён без изменения формул и значений. Новые параметры меняют только новые листы.']]
for row in notes:audit.append(row)
for sheet in [p,c,l,audit,calc]:
 sheet.freeze_panes='D7' if sheet==c else 'B2';sheet.sheet_view.zoomScale=105
 sheet.sheet_view.showGridLines=False
 for row in sheet:
  for cell in row:
   if cell.value is None:continue
   cell.font=Font(name='Calibri',size=12,bold=cell.row in (1,6) if sheet==c else cell.row==1,color='49363A')
   cell.alignment=Alignment(vertical='center',wrap_text=True)
   cell.fill=PatternFill('solid',fgColor='F9EDF1' if cell.data_type=='f' else 'FFF2E6')
   if isinstance(cell.value,(int,float)) or cell.data_type=='f':cell.number_format='#,##0.00;[Red]-#,##0.00;0.00'
   sheet.row_dimensions[cell.row].height=35
 for col in range(1,sheet.max_column+1):sheet.column_dimensions[openpyxl.utils.get_column_letter(col)].width=23
p.column_dimensions['A'].width=33;p.column_dimensions['C'].width=75;audit.column_dimensions['A'].width=30;audit.column_dimensions['B'].width=110
c.auto_filter.ref='A6:R31';w.active=1
validation=DataValidation(type='decimal',operator='between',formula1=0,formula2=100);p.add_data_validation(validation);validation.add('E2:E6')
rates=DataValidation(type='decimal',operator='between',formula1=0,formula2=99.9);p.add_data_validation(rates);rates.add('B3');rates.add('B11')
w.calculation=CalcProperties(calcId=191029,fullCalcOnLoad=True,forceFullCalc=True)
w.save(root/'cloth_calculator.xlsx');print('Created reviewed template and 25 input variants.')
