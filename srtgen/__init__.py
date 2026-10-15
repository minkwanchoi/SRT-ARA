"""SRT-ARA: SW 신뢰성시험 분석 보고서 자동화 도구.

소스코드 주석에 내장한 예외사유 표기법(SRT-...)을 파싱하여
무기체계 SW 개발 및 관리 매뉴얼 부록 7 양식의 보고서(md, hwpx)를 생성한다.

보이는 이름은 SRT-ARA 이고, 내부 이름(패키지, `python -m srtgen`, `srtgen.bat`, `~/.srtgen`, 프로젝트의
`srtgen.json`)은 srtgen 이다. 프로젝트에서 형상관리되는 srtgen.json 을 계속 찾도록 내부 이름은 바꾸지 않는다.
"""

# 버전: ver.X.YY (사용자 확정, ver.0.01 부터). 같은 매뉴얼 판 안의 수정은 0.01씩, 매뉴얼 판이 바뀌면 소수 첫째 자리를
# 올린다(CHANGELOG.md). 산출물·판 이력에는 이 값이 그대로 적힌다.
__version__ = "0.02"
VERSION_LABEL = f"ver.{__version__}"                                 # 보이는 곳의 버전 표기

NAME = "SRT-ARA"                                                     # 화면·문서·버전 표시에 쓰는 이름
NAME_FULL = "Software Reliability Test – Analysis Report Automation"
NAME_KO = "SW 신뢰성시험 분석 보고서 자동화 도구"
