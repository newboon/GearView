#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GearView 빌드 스크립트
PyInstaller를 사용하여 exe 파일 생성
"""

import os
import subprocess
import sys

def install_pyinstaller():
    """PyInstaller 설치"""
    print("PyInstaller 설치 중...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("PyInstaller 설치 완료")
    except subprocess.CalledProcessError as e:
        print(f"PyInstaller 설치 실패: {e}")
        return False
    return True

def build_exe():
    """exe 파일 빌드"""
    print("GearView.exe 빌드 시작...")
    
    # PyInstaller 명령어 구성
    cmd = [
        "pyinstaller",
        "--onefile",  # 단일 exe 파일로 생성
        "--windowed",  # 콘솔 창 숨기기
        "--name=GearView",  # exe 파일명
        "--icon=icon.ico",  # 아이콘 파일 (있는 경우)
        "--add-data=README.md;.",  # README 파일 포함
        "--add-data=LICENSE;.",  # LICENSE 파일 포함
        "--hidden-import=PIL._tkinter_finder",  # Pillow tkinter 호환성
        "--hidden-import=tkinterdnd2",  # tkinterdnd2 모듈
        "GearView.py"
    ]
    
    # 아이콘 파일이 없으면 해당 옵션 제거
    if not os.path.exists("icon.ico"):
        cmd = [arg for arg in cmd if not arg.startswith("--icon")]
    
    try:
        subprocess.check_call(cmd)
        print("\n빌드 완료!")
        print("생성된 파일: dist/GearView.exe")
        return True
    except subprocess.CalledProcessError as e:
        print(f"빌드 실패: {e}")
        return False

def main():
    """메인 함수"""
    print("=== GearView 빌드 스크립트 ===")
    
    # 현재 디렉토리 확인
    if not os.path.exists("GearView.py"):
        print("오류: GearView.py 파일을 찾을 수 없습니다.")
        print("GearView 프로젝트 폴더에서 실행해주세요.")
        return
    
    # PyInstaller 설치
    if not install_pyinstaller():
        return
    
    # exe 빌드
    if build_exe():
        print("\n빌드가 성공적으로 완료되었습니다!")
        print("dist 폴더에서 GearView.exe 파일을 확인하세요.")
    else:
        print("\n빌드에 실패했습니다.")

if __name__ == "__main__":
    main()