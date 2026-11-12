"""Salidas de `probar_factura.py` con 4 facturas reales (noviembre de 2026).

Son el texto OCR que ya pasó por la anonimización de esa versión, tal cual (con su
basura de OCR; de la factura 4 se omitió el texto legal del final), salvo los datos
personales que esa versión dejó escapar, que se
reemplazaron a mano antes de guardarlos en el repo: el nombre del cliente
(factura 5), el del vendedor (factura 4), los últimos 4 dígitos de las tarjetas y
el RRN. Las variantes de OCR de esas líneas ("TAR)", "TARO", "RRN-") se conservan:
son las que la anonimización nueva debe reconocer.

- Facturas 2, 3 y 5: D1, una línea por producto.
- Factura 4: tienda "Aliado Surtimax" operada por Distribuciones Merkamax S.A.S.
  (Bogotá; se ve el logo de Surtimax en la factura), formato multilínea:
  el EAN va arriba de la descripción, la descripción ocupa varias líneas y la
  cantidad está en la columna CANT.
"""

FACTURA_2_D1 = r"""
. x
: ss Sa
Ñ | |
D1 SAS [NIT] Gran contribuyente y Á j
. te .
retenedor de IVA Res.000200/24 TEL: DI800Ó12020 |
; CL 167 No 46 - 48 BOGOTA DC o0O120201
. d CLIENTE: Consuuidor Final [CEDULA]
- Generacion: 2026/11/08 18:42:48 p.
Validacion Dian: 2026-11-08 18:42:51 : . .
| . WI CAN UN VALOR Y CODIGO DESCRIPCION VALOR ID. |
1 TUN 6,550 7702603019160 LONCHITA AMAR 6,5504
2  1UN 3,490 7700304973617 NACHOS CRACHO 3,490 A l
s 3 5 UN 1,650 7700304325207 ARROZ ESTANDA 8,2505.
4 2UN 1,100 7700304263141 BEBIDA DE Y0OG 2,200 A
5 1UN 3,990 7700304337019 PANELA PULVER 3,990 6
6 5UN 550 7702090073065 AGUA SIN GAS 2,750 6
o 773 UN 1,250 7700304871384 LECHE ENTERA 3,750 5 j, .
: 8 1UN 2,400 7700304732357 CREMA DE LECH 2,400 5
. 9 1UN 2,990 7700304083084 SNACK GELATIN 2,990 Á - Mi
10 1UN 3,700 7700304521197 CONSERVA DEP 3,700 A o :
No 11 1UN 5,250 7700304705979 CEREZAS MARRA 5,250 A
12 1UN 5,300 7700304627424 HUEVO DE cooo 5,3005 ,, a
o 13 1UN 6,600 7702025146673 GALLETA SALTI 6,600 A >
— 14 2UN 4,700 7700304751501 LECHE SUPER C 9,4005:
15 2UN 2,00 7700304151462 BOLSA HOGAR.T 4,1004 .--
16 1UN 1,900 7700304980765 ESPONJA MULTI 1,9004,
o , 17 2 UN 2,500 7700304684823 GUANTE DOMEST 5,000 Á
—TOTAL po 77,620
a o FORMA DE PAGO: CONTADO - VALOR PAGADO 77,620
. TARJ CRE/DES $ 77,620
o TAR):4242 [TRANSACCION] RRN-123456 o ,
: [TRANSACCION]
. CAMBIO 0
po RESUKEN DE IMPUESTOS
m'/ TOTAL BASE IVA | No
«6 = EXCLUIDO 6,740 6,740 0
5 = EXENTO: 29,100 29,100 0
] A = 19% y 41,780 35,110 6,670
| Á, 700950 60670 |
e 10. CLIENTE: 'undefined- ] :
, SISTEMA POS ARS DE: NCR COLOMBIA LTDA [NIT]  ' i
FACTURADOR ELECTRONICO:E factura Cadena [NIT]
— o ATENDIDO POR: [NOMBRE]
¿NUI ART ENTREGADOS: 31 [TRANSACCION] a
a ,ResoJucton DIAN 18764094754937 de 20250624 Prefijo 6789 o
/ DE 77202 HASTA 1999999 Vigencia 18 Meses -
Factura Electroni ca Venta 5789207454 | o.
, ENS
= or : a A Es > 5] : Ñ :
. 3 E Aa E ,
[CUFE]
a q20198408 [CUFE]
"""

# El arroz costaba 3,990 y el OCR leyó el total del renglón como 3,905.
FACTURA_3_D1 = r"""
yd :
pi sas N1T[NIT] Gran contribuyente y Agente: |
retepedor de IVA Res.000200/24 [TELEFONO]
/ (1 167 Mo 46 - 48 BOGOTA DC | e
CLIENTE: Consunidor Final [CEDULA] o
—. Generacion: 2026/11/08 16:19:26 |
| / Validacion Dian: 2026-11-08 16:19:29. |
| AT CAN UN VALOR UY CODIGO DESCRIPCION VALOR 10
: | 1. 1 UN 3,190 7700304861026 AZUCAR BLANCA 3,190 C
— | >” 1 UN.” 2,200 7700304492244 CLAVO ENTERO 2,2004.
NX 3 1UN 3,990 7700304100866 ARROZ PREMIUN - 3,905  -
o, TOTAL : 9,380  7-
Ñ - AJUSTE VUELTAS EXACTAS $ 30
FORMA DE PAGO: CONTADO - VALOR PAGADO 9,350 i SS
EFECTIVO $. | 9,400
CAMBIO? . A so 1
10 a, RESUHEN DE, MPUESTOS PASE . |
. 5 = EXENTO 20990. 13,990 E
o Cs 52 3,1190 13,038 - 152
o O 2,200 / 1,849 351
/ ( 8,877 503 7
o 1D. CLIENTE: undefined
o Ñ SISTEMA POS ARS DE: NCR COLOMBIA LTDA [NIT] : '
FACTURADOR ELECTRONICO:E factura Cadena [NIT] |
LT : ATENDIDO POR: [NOMBRE]
SN NUM ART ENTREGADOS: 3 [TRANSACCION] | | |
        Resolucion DTAN 18764094754937 de 20250624 Prefijo:G7B9 | |
| DN DE 77282 HASTA 1999999 Vigencia 18 Meses NO,
OS | Factura Electronica de Venta E o l >
| LA | o, ae
E
RE: So vr E . .
A | PE A poro |
aa o
+ [CUFE]
o [CUFE] A - |
"""

FACTURA_4_MERKAMAX = r"""
MERKAMAR ss MER
M ONES MERKAMAX AS
DISTRIBUCIÓN, 043 .020-0,,
NT 166 815 54779721 . y,
. ELL - 612 . ZA =
DIR: 156406992 p >
TELS: 31 -
e >
DISTRIBUCIONES ,
Lente electrónico :
Docunento a registradora con :
" tiquete de má 05 259383 - Ñ
co sistema Ot 7
rr no on DI n .
p-- eración D .
' autorización de me 2026-05-30 ; | 7
ION 1876411050212 3 hasta POS- 1 .
1” desde POS-2150%% ¿dea 2028-05 5 | :
' 10000000 vigene t
Ñ H 30 Lar .
e .
horno. o
e ; Caja 1
A 841001 - CAJA UNO X .
. VEND: Pedro Gomez Prueba 2 | . . ,
SS HORA: 07:19:17 PM. | : a
: FECHA: 2026-11-08 11-08 9,1 ! o. y
Fecha de validación OIAN: 2025" Jr A D
CLIENTE: CONSUMIDOR FINAL ps : s
: “Y, DESCRIPCIÓN... GNT,,.., VALOR... JOTA co 0 |
: TrOzO2G1eTent | ÓN
: TOALLAS 4 00. .
1 pEQueñta car 23,500 1345
¡ ALMENDRA X100 :
: 7702432759756 .
2 PAN PEQUEÑO Ly 4,200 4,200 8
. COMAPAN 256
/ 7702024040040 .
. NESQUIK 1 r
p 3 CHOCOLATE Car 9+300 9,900 |
“ 2006R :
4 a 6,000 12,000 1 A :
y HEMS , , . |
/ a : |. CHOCOLATE CANT ;
. - ñ a 7702001178049 |
| S  PARMESAANO ANT 13,900 13,900 T , .
] ALPÍN A 1006 |
: 7701101270264 , : .
6 MTDELA TRADI Ey 4,000 4,000 :
: - ..- ZENU XI00GR ¡ ]
7709608971561 , | .
VALLELAC
: 7 MOZARELLA canr 7.200 7,200 8 :
: TAJADO 2306 ñ
7702007079470 :
, os CUOCOLATENA Lar 5.200 5,200 1
: e “ 45GR . .
- : 7707430873855 2 ..
9 NATUMALTA cant 1»500 3,000 8 o
, 7707244560293 | A OTA
10 BIG COLA Muro 39500 1,500 y SU IA
- _. NARNAJA 400ML Pos o 7 SS
o . YX ALQUERIA cant 3300 5,900 T Po;
Su a 20068 o
Ñ o | Ñ 8719200259232 "¡7770 Tm co NS ¡
2 RAMA CON SAL 4,900 4,900 .
¡ 1706R > CANT ! o ¡
: : a AroL1o13s8z45 , 2.300 7 : — o
. NCHERA XS -.. Ñ ,3 Ñ DO :
A =- 1156 CANT 1 :
. 7707268530012 L 4 ,
14 AREPA ,800 1,800 . '
. : CARRIEL x10 CANT , * p
- “15 7702014271836 1 3,300 3,300 y .
SALSA CANT Ñ .
ano MRVOAESA. caos oro tae rn
- : .£,, DESCRIPCIÓN |... ENT... VALOR. TOTAL" : 4
170GR mu ;
. SAN/JORGE á
7702014566147 : : '
. : p 16 TRocrTOS Camy 9800 23,000. 7! Ñ l
. Xx t MANZANA 145CR j
, 7702001086023 . ! i
BON YURT 1
. 17 ZUCARITAS cant “700 0,700 5 h
Ñ 1706 48
18 200s l ; l
- 1
PLASTICA ca 0000 y
HOUEIA DOME ONO SOON OSA LOURDES LO00 80100 VIDEASI8I 0894059 4, Ñ ¡
TOTAL XTEMS:; Me ¿ t
SUBTOTAL
CONTADO cada; TT
% . | CAMBIO: 150,509 ,
: T 19XIVA ' 69,159.66 13,140.30 apor :
il B EXENTO 16,200 0 AOS l $
F SKIVA 3,809.52 190.88, pa e '
A 0% 23,000 0 a 00: -
TOTAL 112,169.19 13,330.62 135,504 ' o q
. : Forma da pago: Contadi Ñ
Medio de pago : Efectivo Ñ 4]
Responsable du IVA. !
a XA
i ¡Gracias por su compral 21
" A y A to
"""

FACTURA_5_D1 = r"""
e a O a : :
D1 SAS [NIT] Gran contribuyente y Agente |
| retenedor de IVA Res.000200/24 [TELEFONO]
CL 167 Mo 46 - 48 BOGOTA DC !
| ¡ CLIENTE: Juan Perez Prueba [CEDULA] e SN
EN y Generacion: 2026/11/08 18:01:39 OS
So, | Validacion Dian: 2026-11-08 18:01:42 o y
4 WI CAN UN VALOR Y CODIGO DESCRIPCION VALOR 10
1 1UN 17,450 7700304280650 YOGURT GRIEGO 17,450 A no.
1 2 1UN 4,450 7700304377589 GELATINA SABO 4,450 A |
o TOTAL EN 21,900 | ¡
FORMA DE PAGO: CONTADO -" VALOR PAGADO 21,900 | o
- TARJ CRE/DES $ | | 21,900 A
TARO: 4242 [TRANSACCION] [TRANSACCION] o
[TRANSACCION] o | a
| | CAMBIO / 0
] RESUMEN DE IMPUESTOS
- 1D ( TOTAL BASE IVA
A = 19% 21,900 18, 403 3,497 :
A l 18,403 3,497
SISTEMA POS ARS DE: NCR COLOMBIA LTDA [NIT]
o - FACTURADOR ELECTRONICO:E factura Cadena [NIT] |
| ATENDIDO POR: [NOMBRE]
NUM ART ENTREGADOS: 2 [TRANSACCION] -
| Resolucion DIAN 18764094753810 de 20250624 Prefijo 6880 | |
o DÉ 41211 HASTA 1999999 Vigencia 18 Moses ,
MN . Factura Electronica ee anal .
[CUFE]
[CUFE]
"""

# Alkosto (otra salida del compañero B): texto completo, porque el encabezado de
# columnas ("$ Articulo IVA Iro Cant Total") no se reconocía y se envió todo a Gemini.
# Se reemplazaron a mano el nombre del cliente (tras "Clánte", la etiqueta mal leída),
# el email (con la @ leída como "é") y el barrio, conservando las lecturas del OCR.
# Formato: la descripción va en la línea de ARRIBA del código y el precio.
FACTURA_6_ALKOSTO = r"""
] aras 17016 3000TA US
Telefono [TELEFONO] —-
vezclientegalkosto.con.co
VU
l
A -
| Factura Electronica de Venta X6601009349
Pedido No. 357738 Caja 24
Fecha 2026/11/02 Hora 09:56:10 --
Clánte PRUEBA FICTICIO NOMBRE APELLIDO 10
[CEDULA]
Cliente: [NOMBRE]
£.C.. OS =
Barrio Ficticio-Sector Prueba
Telfono: [TELEFONO]
Email correopruebaéhotmail.com
Forma de Pago. CONTADO
Medio de Pago. TARJETA DEBITO/CREDITO
Observ:0
$ Articulo IVA Iro Cant Total
1 Leche Álk Entera 1100m1 x6
770102353683/13. 0) 0 ., 67.800
2 Gaseosa Cocacola S/Az 2.5L x2u y
77035850119355. 19 0 1 14.900
3 ChocOCono CremH Pack 6u 5408 =-
77024020853165 19 0 0 18.500
4 Mortadela Jamon RicaChef x5009
| 7707192359041.3 5 0  ) 12.500
S Quesillo Alkosto Tajado 7509
7705994331005.: 0 0 0 24.900
Total Lineas factura: 5
| Subtotal OS 132.672
Valor IVA 5.992 -
Valor Total 138.600
CREDITOGBE CA $ 138.600
Tar/lp IVA V-Base$ V-IVAS E
| 19 11.50 5928 F
9
- Responsable 1.V.A
3 Somos Grandes Contribuyentes
Resoluc. 000270 DIC. 27 de 2024 j
PRGENEDORES DE IVA .
Autorretenedores de Renta
] Res No 0008527 Ago. 24 2.010
Numeración Autorizada slo Habilitada por la
Prefijo X866 del No. 4000001 al 5509000
Numero de [CUFE]
del 2026/07/17 al 2028/07/17?
| Estimado Cliente: [NOMBRE]
politica de cambios en
E uu. alkosto.com/politicas
“4 /cambios-devoluciones-¿/cambios-devoluciones
Software de Facturacion electronica: F3M ?
88111. Fabricado por FAM Technology S.A.S
[NIT] Proveedor tecnologico: FéM
TECHNOLOGY S.A.S :
[CUFE]
1023787f
3 REPRESENTACION GRAFICA DE LA FACTURA
"""

# --- Fotos ORIGINALES del compañero B (sin mejorar), noviembre de 2026 ---
# Salidas de probar_factura.py (texto OCR ya anonimizado). Se reemplazaron a mano la
# dirección de la factura 16 y el nombre de quien atendió en la 20, conservando las
# lecturas del OCR ("DIRECCIONSCL", "Atendido Pur") que la anonimización debe reconocer.

# 3.jpeg: enfoque 461, pero el OCR es basura. No debe llegar a Gemini.
FACTURA_B3_ILEGIBLE = r"""
Q.. 1
E,
" y a
EL ero
had Se NAAA rios
5 o o .
o Ma dr a o
do RN .
Le IO TO
Fa a A re e 5D, *
a y ho a a CAS
AN >
dl ... )
Un adas o A 7 ,
bu AN ol
A A p
non” pt MESSAGE uy i .
o SAA pro
ALL] ce unos rro 00; bescrincida partera 1
: PU ear tem : IN
E e VOS E da ea oa í
o — iran E E A E] po
. 1.07 £a 105G0- CION9-6 TUCZNE Bana OS e : 1
DA O E ES eos mn |
RE Otecritinación 20 Jeouestos A
Y Ñ emsersoción 16 rss Irstos A :
do e Eme eo. A 4
AO) A toteies 132.39 ( a '
0 da TON 12. a
Lt 1 ERA: 1:2.109 Alo a
des - 26. TA 8tA 166 LIO 12.19 Pa
E poa o,
A ac Vesetasatricar poi
O E Saa ratels | Ho I 1
AT RSOSIAEA-Mnean Sesto: HN:CCANLAS 9 Comicos IN
ETT Ea ts Scissor: Solución Free GAO H I- ¡
o O pops l
AAA rta uscolagoca: Be Cortaltios MN mt. Loa, .
PG] sd, 1006 Mosela 4 Amor Uco. Sa |
Lcd y po! |
1 1] i i co Ñ :
A 0 Loi
En trago adoos
a 1 ES:
A e amd y
A col
ep y al
Co 1001
E: [a] SIE al
11 A
a
"""

# 4.jpeg: enfoque 729, OCR basura. De "Ltda Yuca, o ENIMGM0O: 31.000" Gemini sacó un
# producto "Yuca $31,000", y "ara" en la basura hacía detectar el supermercado Ara.
FACTURA_B4_ILEGIBLE = r"""
LT tm TT ON AN
| tdo : " |
py mad Koa DIA $ rd SALES ES ' :
Ad mms A o rose 1 a
2 ¡Ue so , A IDE , ! p
EXA a a a : ;
“QA diana de ooo » LOAN Le toa ara . :
Ñ S EA nn 104. ao A Ñ d
> Dolo o E RASO IA $ te, :
¡[O OE: o LA rs Pa . t
Se A A ae pa ICI odie dor /
O Ari |
OA ERES Y) A |
EA OS pt
Lo, + Ti OA TE ÓN r
o a EI on 1000 ZIDNZI GAL rusgnS Desa M2 a ,
TS ¡A A A
” Oiscrintreziór de Jepastes ÓN .
mor HA las Descripcion 19 losa mer Do :
A A: 3 Me nm e j
un LM 1 15.00 1.0 ORTO
Es ), PUNA y Totales Des 6355 ÓN :
— LO qe L su: nO aL
Ltda Yuca, o ENIMGM0O: 31.000 Lo 7
1 .. o. HORTA TES CEIC » us IS
pts Le mucama 1 0IgEsSI8IDO SEC “O/O0202S , A :
=p 2 DO o ASE SIAM MEAR O A:
ps hoerscarto cal eoftaseacIC0-ntos 01 "oeestor.eti-ES Ñ =.T
: Pa Ate 2 art Secta: IACEATILES A COM ICOCIOn arm :
OD - dar Po: rin: o Qretrrtear: Selucioses Foc GAS + Lo Ñ
a . , ml 00 135 46101 A] |
Deo qt Penas Moctaa: e Eos AS e pam TT,
7 O EPIA POS: 100 deco Lied Ye lord ¿
A :
SRT - J ET RTS ES 7 dar po, ¡
217 455 tos
an A po la ol
A => a
e ea
ok - 5 el
> ponlo Ps a de]
A AS el
po ES Aa
: IA l e a o
a A A
i Ti 2 A a no.
A [ dla dos AS Lo uni)
” 4 PT
"""

# 16.jpeg: Ara (Jerónimo Martins), legible a medias. Gemini inventó los EAN a partir de
# "TIOAZE96300ZA" (devolvió 7702963002498).
FACTURA_B16_ARA = r"""
A EN do
ed a e
e NA TIENDAS NRA JLRONIMO MIRTINS COLUPBIA S.A.S. [NIT] ¡AN «Ny
DU E,s Y GAN CONTRIBUYENTE RES. 1DOCO0/24 AGENTE RETENEDOR UC Jun AUTOR.LE OEA
¿iros 3 RENTA RES.O00292/2014 TEL 3COYIZAS2I > EA
a Y «+ FACTURA ELECTRONICA DE VENTA N: ATEAVTZA1B AN A IE
us EE do GENERACION: 2026-10-24 10:44:35 — WALIDACION DIAN: 2026-10-24 10:44:36 E SAD
A y Val CLIENTE: CONSUMILOR FINAL IDENTIFICACION NO.2 222222022222 NY : AÚN
2 afro d DIRECCIONSCL 00 Bis 00-000 FORMA FAGO: CONTADO — TOTAL ART:3 Ñ TN Y
IIS Y E CoDiGu DESCRIP IT A TN O EN
EE Í 1 TIOAZE96300ZA YESURT GRIEGO 13 LUN 20.520 20.520 AN
Pedo ph 2 TIOAZERZADISZ DUESO CUAJADA 4 € 2 UN 9.450 E
a Fo 3 osze91ozos ACENTE OL IV 504 1 UN 16.950 16.950 A
AA WOIALESARECARGOS + 0 DESCUENTOS: -0 FACTURA» 56.00 [.itio 0:
¡Ufo 1 ¿RO HRECARGOS: Inouestos al Consuna — PEDIO/PNGO: Tari Detyfred: 58.370 A
ES 3.4 de Cervezas, Licores y Cigarrillos A,
Cn, Total SEI [ri
ta 7 DESCRIPCION DASE/CANTIDAD IUAZINP CONSUMO e
O dl 31.487 0 AA
A AN - : 18.900 0 ETA
Da TOJAL IMPUESTOS: O IN
E, Meg Su TracklD es: CS
MA
a 220829202610241044001500010472 AN
. NN GuruSoftSAS N1T991014885 Jerémimo Martins Colorbia SAS [NIT] ES 5
EN . SoftusreEduc Resoluc ionf187E4102420801 de 2025-12-02 vigencia hasta ES
Lea 2027-06-02 Habillta 4724 Rango 125675 a 333993 . o EA ,
vr $. [CUFE]
.. y +] [CUFE] CI
>. te *
Lo POE RIA o :
, ot Ss, EEES | CS
IÓ E TRAS AS
d 1) RP OA
bi ñ 229879 2026-10-24 10:44 0015 0001 0472 ÓN
NE
"""

# 20.jpeg: enfoque 277 (el más bajo de los cuatro), pero se lee a medias.
FACTURA_B20 = r"""
A o
[NIT] PLAN INVESTMENTS 3.0.3 CHA III DL PROTA A V
(133
Cliente: [NOMBRE]
inctora electronica de venta 1:ESC308708 .
Cencración 01 11 20%b 0:95:59 y.1. Atendido Pur pedro prueba FO
Fecha Validacion OLA 2026-11-01 17:35:59 POS $13001
110 Doser Tec 1un ut Cantidad — Valor Inbp
1 v001402 GRSEUSA COLA Lo SS un 4 93.430 1U
2 OGUSAO ARON SAMIGUCIE 2ENU vub 1 $10.490 16
3 0001178 QUESTO TAJADO 1ELE UND 4 $10.430 EX
4 6603134 MucbL LA IRTLEREAL SÁ Uno 1 $7.690 EX .
y 0003137 Pan 1alabo FRUTOS DE Unt1 s0.:30 EX
¡Total ifens: 5
| Turna de Paso: Total $40.450 ar
tiedio de Paso: tfuctivo $100.000
] Caubio $59.550
¿M6 Couprá base/ [op InPTO
y - 13,960 11.748 3.232
CT 26.410 26.470 0
40.450 30.218 2.232
— NoMAUSIZN25) DILOS02S ALA 022 QNL.ESUSL a Es0 200
aya Lertol Ss COMET ES Y MaS 1UNL Lunes bt 10
AS gls ErbLo Y SIS I1MGS ANILURADOS 5.0. AU a 01d 2 0
4d tota hadena S.A, MI). ui 040,994 0
Facturado: Cuumidar Eimalo Due RIAS
A o |
"""
