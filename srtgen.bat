@echo off
chcp 949 >nul
rem SRT-ARA(SW 신뢰성시험 분석 보고서 자동화 도구): 확인·편집 화면을 띄운다(이 PC에서만 접속).
rem 두 번 누르면 프로젝트 목록이 있는 첫 화면이 열린다. 폴더나 프로젝트 파일을 이 파일에 끌어다 놓으면 그것을 연다.
rem Python은 실제로 실행해 보고 고른다: 폐쇄망용 묶음에 든 python\python.exe가 먼저이고, 없거나 실행되지 않으면 PC의 python, py -3 순서.
rem Windows의 python 실행 별칭(Microsoft Store로 연결되는 것)은 where로는 찾아지지만 돌지 않으므로 where로 고르지 않는다.
rem 이 파일은 CP949다. cmd는 줄마다 지금 코드 페이지로 읽으므로 맨 앞에서 949로 맞추고(UTF-8 베타 설정 PC 대비),
rem 한글 안내는 chcp 65001 앞에서 내보낸다. 65001 뒤에는 영문만 둔다.
cd /d "%~dp0"
set "SRT_PY="
if exist "python\python.exe" (
  "python\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
  if not errorlevel 1 set "SRT_PY=python\python.exe"
)
if not defined SRT_PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
  if not errorlevel 1 set "SRT_PY=python"
)
if not defined SRT_PY (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
  if not errorlevel 1 set "SRT_PY=py -3"
)
if not defined SRT_PY (
  echo Python 3.9 이상을 찾지 못했습니다.
  echo Python이 함께 든 폐쇄망용 묶음 zip을 쓰거나, python.org의 Windows 설치 파일로 Python을 설치한 뒤 다시 실행하십시오.
  echo 자세한 것은 README.md의 '폐쇄망 PC에 설치'를 보십시오.
  pause
  exit /b 1
)
chcp 65001 >nul
title SRT-ARA (Software Reliability Test - Analysis Report Automation)
%SRT_PY% -X utf8 -m srtgen serve %*
if errorlevel 1 pause
