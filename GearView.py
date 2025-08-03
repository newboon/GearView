import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ExifTags
import os
import shutil
import re # 파일명으로 부적합한 문자 제거용
import subprocess
import platform
import threading
import queue
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    print("Warning: tkinterdnd2 not available. Drag and drop functionality will be disabled.")

# --- 전역 변수 및 데이터 구조 ---
source_folders = []
target_folder = ""
# scanned_files_by_name: Key: filename, Value: filepath (파일명 중복 시 첫 번째 파일만)
scanned_files_by_name = {}
# files_by_camera_lens: Key: camera_model, Value: dict {lens_model: [filepaths]}
files_by_camera_lens = {}
# 현재 정렬 모드 ('count' 또는 'name')
current_sort_mode = 'count'
# 스캔 결과를 위한 큐
scan_result_queue = queue.Queue()

# --- EXIF 처리 함수 ---
def get_exif_data(filepath):
    """ 이미지 파일에서 EXIF 데이터를 읽어옵니다. """
    try:
        img = Image.open(filepath)
        exif_data_pil = img._getexif() # Pillow 내부 형식의 EXIF 데이터
        if exif_data_pil is None:
            return {}

        exif = {}
        for tag_id, value in exif_data_pil.items():
            tag_name = ExifTags.TAGS.get(tag_id, tag_id)
            exif[tag_name] = value
        return exif
    except Exception as e:
        print(f"Error reading EXIF for {filepath}: {e}")
        return {}

def get_lens_info(exif_data):
    """ EXIF 데이터에서 렌즈 모델 정보를 추출합니다. """
    lens_model = exif_data.get('LensModel')
    if lens_model:
        # 간혹 바이트 문자열로 반환되는 경우 디코딩
        if isinstance(lens_model, bytes):
            try:
                lens_model = lens_model.decode('utf-8', errors='replace').strip()
            except UnicodeDecodeError:
                lens_model = str(lens_model) # 디코딩 실패 시 문자열로 강제 변환
        return str(lens_model).strip() # 공백 제거

    lens_make = exif_data.get('LensMake')
    # 다른 렌즈 관련 태그들을 조합하여 정보를 만들 수도 있습니다.
    # 예: FocalLength, FNumber 등
    # 여기서는 LensModel이 없으면 LensMake라도 반환하거나, 더 복잡한 로직을 추가할 수 있습니다.
    if lens_make:
        if isinstance(lens_make, bytes):
            try:
                lens_make = lens_make.decode('utf-8', errors='replace').strip()
            except UnicodeDecodeError:
                lens_make = str(lens_make)
        return f"Make: {str(lens_make).strip()}"

    return "No lens info"

def get_camera_info(exif_data):
    """ EXIF 데이터에서 카메라 모델 정보를 추출합니다. """
    camera_model = exif_data.get('Model')
    camera_make = exif_data.get('Make')
    
    if camera_model:
        # 간혹 바이트 문자열로 반환되는 경우 디코딩
        if isinstance(camera_model, bytes):
            try:
                camera_model = camera_model.decode('utf-8', errors='replace').strip()
            except UnicodeDecodeError:
                camera_model = str(camera_model)
        
        camera_model = str(camera_model).strip()
        
        # 제조사 정보가 있고 모델명에 제조사가 포함되지 않은 경우 조합
        if camera_make:
            if isinstance(camera_make, bytes):
                try:
                    camera_make = camera_make.decode('utf-8', errors='replace').strip()
                except UnicodeDecodeError:
                    camera_make = str(camera_make)
            
            camera_make = str(camera_make).strip()
            
            # 모델명에 제조사명이 이미 포함되어 있는지 확인
            if camera_make.lower() not in camera_model.lower():
                return f"{camera_make} {camera_model}"
        
        return camera_model
    
    # 모델 정보가 없으면 제조사라도 반환
    if camera_make:
        if isinstance(camera_make, bytes):
            try:
                camera_make = camera_make.decode('utf-8', errors='replace').strip()
            except UnicodeDecodeError:
                camera_make = str(camera_make)
        return f"Make: {str(camera_make).strip()}"
    
    return "No camera info"

# --- 파일 스캔 및 분석 함수 ---
def scan_and_analyze_files():
    if not source_folders:
        messagebox.showwarning("Warning", "Please select source folders first.")
        return
    
    # 스캔 버튼 비활성화
    scan_button.config(state='disabled')
    
    # 프로그레스바 표시
    progress_bar.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
    progress_bar.config(mode='indeterminate')
    progress_bar.start()
    
    # 백그라운드에서 스캔 실행
    scan_thread = threading.Thread(target=scan_files_background)
    scan_thread.daemon = True
    scan_thread.start()
    
    # 결과 확인을 위한 타이머 시작
    window.after(100, check_scan_result)

def scan_files_background():
    global scanned_files_by_name, files_by_camera_lens, scan_result_queue
    
    try:
        scanned_files_by_name.clear()
        files_by_camera_lens.clear()
        
        file_count = 0
        for folder_path in source_folders:
            for root, _, files in os.walk(folder_path):
                for file in files:
                    if file.lower().endswith(('.jpg', '.jpeg')):
                        file_path = os.path.join(root, file)
                        # 파일명 기준 중복 처리: 이미 같은 이름의 파일이 있다면 건너뜀
                        if file not in scanned_files_by_name:
                            scanned_files_by_name[file] = file_path
                            file_count += 1
                            # EXIF 분석
                            exif = get_exif_data(file_path)
                            lens_info = get_lens_info(exif)
                            camera_info = get_camera_info(exif)

                            # 카메라별 > 렌즈별 2단계 분류
                            if camera_info not in files_by_camera_lens:
                                files_by_camera_lens[camera_info] = {}
                            
                            if lens_info not in files_by_camera_lens[camera_info]:
                                files_by_camera_lens[camera_info][lens_info] = []
                            
                            files_by_camera_lens[camera_info][lens_info].append(file_path)
        
        # 결과를 큐에 넣기
        total_lens_groups = sum(len(lenses) for lenses in files_by_camera_lens.values())
        result_message = f"Analysis complete: {len(scanned_files_by_name)} unique JPG files processed. {len(files_by_camera_lens)} cameras, {total_lens_groups} lens groups."
        scan_result_queue.put(("success", result_message))
        
    except Exception as e:
        scan_result_queue.put(("error", str(e)))

def check_scan_result():
    try:
        result_type, message = scan_result_queue.get_nowait()
        
        # 프로그레스바 숨기기
        progress_bar.stop()
        progress_bar.pack_forget()
        
        # 스캔 버튼 다시 활성화
        scan_button.config(state='normal')
        
        if result_type == "success":
            update_treeview()
            status_label.config(text=message)
            if not scanned_files_by_name:
                messagebox.showinfo("Info", "No JPG files found in selected folders.")
        else:
            status_label.config(text="Error occurred during scanning.")
            messagebox.showerror("Error", f"An error occurred: {message}")
            
    except queue.Empty:
        # 아직 결과가 없으면 다시 확인
        window.after(100, check_scan_result)

def clear_analysis_results():
    """분석 결과 리스트 초기화"""
    global scanned_files_by_name, files_by_camera_lens
    scanned_files_by_name.clear()
    files_by_camera_lens.clear()
    update_treeview()
    clear_image_preview()
    status_label.config(text="Analysis results cleared.")


# --- GUI 업데이트 함수 ---
def update_source_folder_list():
    source_folder_listbox.delete(0, tk.END)
    for folder in source_folders:
        source_folder_listbox.insert(tk.END, folder)

# 분류 모드 전환 함수 제거됨 - 이제 카메라 > 렌즈 2단계 고정 구조

def on_sort_mode_change():
    global current_sort_mode
    current_sort_mode = sort_mode_var.get()
    # 트리뷰 업데이트
    update_treeview()

def on_tree_double_click(event):
    """ 트리뷰 아이템 더블클릭 시 파일 열기 """
    item = result_tree.selection()[0] if result_tree.selection() else None
    if not item:
        return
    
    # 파일 아이템인지 확인 (values가 있고 파일 경로가 포함된 경우)
    values = result_tree.item(item, 'values')
    if values and len(values) > 0:
        file_path = values[0]
        if os.path.isfile(file_path):
            try:
                # Windows에서 기본 프로그램으로 파일 열기
                if platform.system() == 'Windows':
                    os.startfile(file_path)
                elif platform.system() == 'Darwin':  # macOS
                    subprocess.run(['open', file_path])
                else:  # Linux
                    subprocess.run(['xdg-open', file_path])
            except Exception as e:
                messagebox.showerror("Error", f"Cannot open file: {str(e)}")

def on_tree_single_click(event):
    """트리뷰 단일 클릭 시 이미지 미리보기 업데이트"""
    selection = result_tree.selection()
    if selection:
        item = selection[0]
        tags = result_tree.item(item, "tags")
        
        # 파일 아이템인 경우
        if 'file_item' in tags:
            file_path = result_tree.item(item, "values")[0] if result_tree.item(item, "values") else None
            if file_path and os.path.exists(file_path):
                update_image_preview(file_path)
            else:
                clear_image_preview()
        # 카메라 그룹이나 렌즈 그룹인 경우 첫 번째 파일 표시
        elif 'camera_group' in tags or 'lens_group' in tags:
            # 하위 파일 아이템들 중 첫 번째 찾기
            first_file_path = find_first_file_in_group(item)
            if first_file_path:
                update_image_preview(first_file_path)
            else:
                clear_image_preview()
        else:
            clear_image_preview()
    else:
        clear_image_preview()

def find_first_file_in_group(group_item):
    """그룹 아이템에서 첫 번째 파일 경로를 찾습니다 (수정 날짜 기준)"""
    children = result_tree.get_children(group_item)
    
    for child in children:
        child_tags = result_tree.item(child, "tags")
        
        # 파일 아이템인 경우
        if 'file_item' in child_tags:
            file_path = result_tree.item(child, "values")[0] if result_tree.item(child, "values") else None
            if file_path and os.path.exists(file_path):
                return file_path
        # 하위 그룹인 경우 재귀적으로 탐색
        else:
            result = find_first_file_in_group(child)
            if result:
                return result
    
    return None

def update_image_preview(file_path):
    """이미지 미리보기 업데이트"""
    try:
        # 이미지 열기 및 크기 조정
        image = Image.open(file_path)
        # 미리보기 크기에 맞게 조정 (비율 유지)
        preview_size = (200, 150)
        image.thumbnail(preview_size, Image.Resampling.LANCZOS)
        
        # tkinter PhotoImage로 변환
        from tkinter import PhotoImage
        import io
        
        # PIL Image를 PhotoImage로 변환하기 위해 임시 저장
        bio = io.BytesIO()
        image.save(bio, format='PNG')
        bio.seek(0)
        
        # PhotoImage 생성
        photo = PhotoImage(data=bio.getvalue())
        
        # 라벨에 이미지 설정
        preview_label.configure(image=photo)
        preview_label.image = photo  # 참조 유지
        
        # 파일명 표시
        filename = os.path.basename(file_path)
        filename_label.configure(text=filename)
        
    except Exception as e:
        clear_image_preview()
        print(f"이미지 미리보기 오류: {e}")

def clear_image_preview():
    """이미지 미리보기 지우기"""
    preview_label.configure(image="")
    preview_label.image = None
    filename_label.configure(text="Please select an image")

def on_tree_right_click(event):
    """ 트리뷰 아이템 우클릭 시 컨텍스트 메뉴 표시 """
    item = result_tree.identify_row(event.y)
    if not item:
        return
    
    # 파일 아이템인지 확인
    values = result_tree.item(item, 'values')
    if values and len(values) > 0:
        file_path = values[0]
        if os.path.isfile(file_path):
            # 컨텍스트 메뉴 생성
            context_menu = tk.Menu(window, tearoff=0)
            context_menu.add_command(label="Open Folder", command=lambda: open_file_folder(file_path))
            
            # 메뉴 표시
            try:
                context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                context_menu.grab_release()

def open_file_folder(file_path):
    """ 파일이 있는 폴더 열기 """
    try:
        # Windows에서 탐색기로 폴더 열기
        if platform.system() == 'Windows':
            # 경로를 정규화하고 역슬래시로 변환
            normalized_path = os.path.normpath(file_path)
            subprocess.run(f'explorer /select,"{normalized_path}"', shell=True)
        elif platform.system() == 'Darwin':  # macOS
            subprocess.run(['open', '-R', file_path])
        else:  # Linux
            folder_path = os.path.dirname(file_path)
            subprocess.run(['xdg-open', folder_path])
    except Exception as e:
        messagebox.showerror("Error", f"Cannot open folder: {str(e)}")

def update_treeview():
    """ 트리뷰를 카메라 > 렌즈 2단계 계층 구조로 업데이트합니다. """
    # 기존 아이템 삭제
    for item in result_tree.get_children():
        result_tree.delete(item)

    if not files_by_camera_lens:
        return
    
    # 카메라별 정렬 적용
    if current_sort_mode == 'count':
        # 총 파일 수 기준 내림차순 정렬 (많은 것이 위로)
        sorted_cameras = sorted(files_by_camera_lens.items(), 
                               key=lambda x: sum(len(files) for files in x[1].values()), 
                               reverse=True)
    else:
        # 카메라 이름 기준 오름차순 정렬 (ABC 순)
        sorted_cameras = sorted(files_by_camera_lens.items(), key=lambda x: x[0].lower())
    
    for camera_info, lenses_dict in sorted_cameras:
        # 카메라별 총 파일 수 계산
        total_files = sum(len(files) for files in lenses_dict.values())
        camera_node = result_tree.insert("", tk.END, 
                                       text=f"{camera_info} ({total_files} files, {len(lenses_dict)} lenses)", 
                                       open=False, tags=('camera_group',))
        
        # 렌즈별 정렬 적용
        if current_sort_mode == 'count':
            # 파일 수 기준 내림차순 정렬
            sorted_lenses = sorted(lenses_dict.items(), key=lambda x: len(x[1]), reverse=True)
        else:
            # 렌즈 이름 기준 오름차순 정렬
            sorted_lenses = sorted(lenses_dict.items(), key=lambda x: x[0].lower())
        
        for lens_info, file_paths in sorted_lenses:
            lens_node = result_tree.insert(camera_node, tk.END, 
                                         text=f"{lens_info} ({len(file_paths)} files)", 
                                         open=False, tags=('lens_group',))
            
            # 파일 노드들 추가 (수정 날짜 기준 정렬)
            sorted_files = sorted(file_paths, key=lambda x: os.path.getmtime(x), reverse=True)
            for file_path in sorted_files:
                filename = os.path.basename(file_path)
                result_tree.insert(lens_node, tk.END, text=filename, values=(file_path,), tags=('file_item',))

# --- 파일 작업 함수 ---
def sanitize_foldername(name):
    """ 파일명/폴더명으로 사용할 수 없는 문자를 제거하거나 대체합니다. """
    # Windows에서 폴더명으로 사용할 수 없는 문자: < > : " / \ | ? *
    # 그리고 NUL 문자 (보통 직접 입력되진 않음)
    # 여기서는 간단히 언더스코어로 대체합니다.
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)

def process_files(action):
    global target_folder
    if not target_folder:
        messagebox.showwarning("Warning", "Please select target folder first.")
        return

    selected_items = result_tree.selection()
    if not selected_items:
        messagebox.showwarning("Warning", "Please select files to move or copy.\n(Camera groups, lens groups, or individual files can be selected)")
        return

    # Confirm user's action choice with special warning for move operation only
    action_verb = "move" if action == "move" else "copy"
    if action == "move":
        confirm_msg = f"⚠️ WARNING: MOVE OPERATION ⚠️\n\n"
        confirm_msg += f"This will PERMANENTLY MOVE files from their original location.\n"
        confirm_msg += f"The files will NO LONGER exist in the source folders after this operation.\n\n"
        confirm_msg += f"Are you absolutely sure you want to MOVE the selected files?\n\n"
        confirm_msg += f"Target folder: {target_folder}\n\n"
        confirm_msg += f"Click 'Yes' only if you are certain you want to move (not copy) the files."
        if not messagebox.askyesno("⚠️ CONFIRM MOVE OPERATION", confirm_msg):
            return
    # copy 작업은 확인 대화상자 없이 바로 진행

    # Check if any camera group is selected to show folder organization dialog
    has_camera_group = False
    for item_id in selected_items:
        tags = result_tree.item(item_id, "tags")
        if 'camera_group' in tags:
            has_camera_group = True
            break
    
    # Show folder organization dialog if camera group is selected
    organize_by_lens = False
    if has_camera_group:
        dialog = tk.Toplevel(window)
        dialog.title("Folder Organization")
        dialog.geometry("400x200")
        dialog.resizable(False, False)
        dialog.transient(window)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        dialog_result = {'organize_by_lens': False, 'confirmed': False}
        
        ttk.Label(dialog, text="How would you like to organize the files?", font=('Arial', 10)).pack(pady=15)
        
        option_var = tk.StringVar(value="no_organize")
        
        ttk.Radiobutton(dialog, text="Organize by lens (create lens subfolders)", 
                       variable=option_var, value="organize_by_lens").pack(pady=5, padx=(50, 0), anchor=tk.W)
        ttk.Radiobutton(dialog, text="Don't organize by lens (all files in camera folder)", 
                       variable=option_var, value="no_organize").pack(pady=5, padx=(50, 0), anchor=tk.W)
        
        def on_ok():
            dialog_result['organize_by_lens'] = (option_var.get() == "organize_by_lens")
            dialog_result['confirmed'] = True
            dialog.destroy()
        
        def on_cancel():
            dialog.destroy()
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=20)
        ok_button = ttk.Button(button_frame, text="OK", command=on_ok, width=10)
        ok_button.pack(side=tk.LEFT, padx=10)
        cancel_button = ttk.Button(button_frame, text="Cancel", command=on_cancel, width=10)
        cancel_button.pack(side=tk.LEFT, padx=10)
        
        dialog.wait_window()
        
        if not dialog_result['confirmed']:
            return
        
        organize_by_lens = dialog_result['organize_by_lens']

    status_label.config(text=f"Processing files ({action_verb})...")
    window.update_idletasks()

    processed_count = 0
    error_count = 0
    files_to_process = []

    # 선택된 아이템(카메라/렌즈 그룹 또는 개별 파일)으로부터 실제 파일 경로 목록 생성
    for item_id in selected_items:
        tags = result_tree.item(item_id, "tags")
        if 'camera_group' in tags: # 카메라 그룹이 선택된 경우
            camera_name_raw = result_tree.item(item_id, "text").split(' (')[0]
            # 카메라 그룹의 모든 렌즈 그룹을 순회
            for lens_id in result_tree.get_children(item_id):
                lens_name_raw = result_tree.item(lens_id, "text").split(' (')[0]
                # 각 렌즈 그룹의 모든 파일을 가져옴
                for file_id in result_tree.get_children(lens_id):
                    file_path = result_tree.item(file_id, "values")[0]
                    files_to_process.append((file_path, camera_name_raw, lens_name_raw, organize_by_lens))
        elif 'lens_group' in tags: # 렌즈 그룹이 선택된 경우
            lens_name_raw = result_tree.item(item_id, "text").split(' (')[0]
            parent_id = result_tree.parent(item_id)
            camera_name_raw = result_tree.item(parent_id, "text").split(' (')[0]
            # 해당 렌즈 그룹의 모든 파일을 가져옴
            for file_id in result_tree.get_children(item_id):
                file_path = result_tree.item(file_id, "values")[0]
                files_to_process.append((file_path, camera_name_raw, lens_name_raw, True))  # 렌즈 그룹 선택시 항상 렌즈별 폴더 생성
        elif 'file_item' in tags: # 개별 파일이 선택된 경우
            file_path = result_tree.item(item_id, "values")[0]
            lens_id = result_tree.parent(item_id)
            camera_id = result_tree.parent(lens_id)
            lens_name_raw = result_tree.item(lens_id, "text").split(' (')[0]
            camera_name_raw = result_tree.item(camera_id, "text").split(' (')[0]
            # 중복 추가 방지
            if not any(f[0] == file_path for f in files_to_process):
                files_to_process.append((file_path, camera_name_raw, lens_name_raw, True))  # 개별 파일 선택시 항상 렌즈별 폴더 생성


    # 중복 제거 (만약 그룹과 그 안의 파일이 동시에 선택된 경우)
    unique_files_to_process = []
    seen_paths = set()
    for path, camera_name, lens_name, organize_lens in files_to_process:
        if path not in seen_paths:
            unique_files_to_process.append((path, camera_name, lens_name, organize_lens))
            seen_paths.add(path)
    files_to_process = unique_files_to_process


    if not files_to_process:
        messagebox.showinfo("Info", "No files selected for processing.")
        status_label.config(text="Ready")
        return

    for source_path, camera_name_raw, lens_name_raw, organize_by_lens_flag in files_to_process:
        try:
            # 대상 폴더 구조 생성 (렌즈별 폴더 나누기 옵션에 따라)
            sanitized_camera_name = sanitize_foldername(camera_name_raw)
            camera_target_folder = os.path.join(target_folder, sanitized_camera_name)
            
            if organize_by_lens_flag:
                # 렌즈별 폴더 나누기: 카메라 > 렌즈 2단계 폴더 구조
                sanitized_lens_name = sanitize_foldername(lens_name_raw)
                final_target_folder = os.path.join(camera_target_folder, sanitized_lens_name)
            else:
                # 렌즈별 폴더 나누지 않기: 카메라 폴더에 모든 파일
                final_target_folder = camera_target_folder
            
            os.makedirs(final_target_folder, exist_ok=True)

            filename = os.path.basename(source_path)
            destination_path = os.path.join(final_target_folder, filename)

            # 대상 경로에 동일 파일명 존재 시 처리 (덮어쓰지 않고 (1), (2) 추가)
            counter = 1
            base, ext = os.path.splitext(destination_path)
            while os.path.exists(destination_path):
                destination_path = f"{base}({counter}){ext}"
                counter += 1

            if action == "move":
                shutil.move(source_path, destination_path)
            elif action == "copy":
                shutil.copy2(source_path, destination_path) # copy2는 메타데이터도 보존 시도

            processed_count += 1
            status_label.config(text=f"{action_verb.capitalize()}: {filename} ({processed_count}/{len(files_to_process)})")
            window.update_idletasks()

        except Exception as e:
            error_count += 1
            print(f"Error {action_verb}ing {source_path} to {destination_path}: {e}")
            # 오류 발생 시 메시지 박스 (너무 많이 뜨면 불편하므로, 로그로 대체하거나 요약 보고)

    # 작업 완료 후, 이동된 파일은 Treeview에서 제거 (또는 상태 업데이트)
    if action == "move":
        scan_and_analyze_files() # 이동 후 목록을 다시 스캔하여 갱신

    summary_msg = f"{action_verb.capitalize()} operation completed.\nSuccess: {processed_count} files\nFailed: {error_count} files"
    messagebox.showinfo("Operation Complete", summary_msg)
    status_label.config(text="Ready")


# --- GUI 이벤트 핸들러 ---
def add_source_folder():
    folder_selected = filedialog.askdirectory()
    if folder_selected and folder_selected not in source_folders:
        source_folders.append(folder_selected)
        update_source_folder_list()

def remove_source_folder():
    selected_indices = source_folder_listbox.curselection()
    if not selected_indices:
        messagebox.showwarning("Warning", "Please select source folders to remove from the list.")
        return
    # 뒤에서부터 삭제해야 인덱스 문제 없음
    for index in reversed(selected_indices):
        source_folders.pop(index)
    update_source_folder_list()

def select_target_folder():
    global target_folder
    folder_selected = filedialog.askdirectory()
    if folder_selected:
        target_folder = folder_selected
        target_folder_label.config(text=f"Target folder: {target_folder}")

# --- 드래그 앤 드롭 이벤트 핸들러 ---
def on_source_drop(event):
    """ 원본 폴더 리스트박스에 드롭된 폴더 처리 """
    files = window.tk.splitlist(event.data)
    for file_path in files:
        if os.path.isdir(file_path) and file_path not in source_folders:
            source_folders.append(file_path)
            source_folder_listbox.insert(tk.END, file_path)
            update_source_folder_list()

def on_target_drop(event):
    """ 대상 폴더 영역에 드롭된 폴더 처리 """
    files = window.tk.splitlist(event.data)
    for file_path in files:
        if os.path.isdir(file_path):
            global target_folder
            target_folder = file_path
            target_folder_label.config(text=f"Target folder: {target_folder}")
            break  # 첫 번째 폴더만 사용

# --- GUI 생성 ---
if DND_AVAILABLE:
    window = TkinterDnD.Tk()
else:
    window = tk.Tk()
window.title("GearView")
window.geometry("650x700") # 창 크기 조절 - 너비 축소

# 프레임 구성
top_frame = ttk.Frame(window, padding="10")
top_frame.pack(fill=tk.X)

middle_frame = ttk.Frame(window, padding="10")
middle_frame.pack(fill=tk.BOTH, expand=True)

bottom_frame = ttk.Frame(window, padding="10")
bottom_frame.pack(fill=tk.X)

status_frame = ttk.Frame(window, padding="5") # 상태 표시줄 프레임
status_frame.pack(fill=tk.X, side=tk.BOTTOM)


# --- 상단 프레임 (원본 폴더) ---
# Source folder section
source_folder_frame = ttk.LabelFrame(top_frame, text="1. Source Folders (Drag & Drop)", padding="10")
source_folder_frame.pack(fill=tk.BOTH, expand=True)

source_folder_listbox = tk.Listbox(source_folder_frame, selectmode=tk.EXTENDED, height=5)
source_folder_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
# 스크롤바 추가
source_scrollbar = ttk.Scrollbar(source_folder_frame, orient=tk.VERTICAL, command=source_folder_listbox.yview)
source_scrollbar.pack(side=tk.LEFT, fill=tk.Y)
source_folder_listbox.config(yscrollcommand=source_scrollbar.set)

# 드래그 앤 드롭 바인딩 (원본 폴더)
if DND_AVAILABLE:
    source_folder_listbox.drop_target_register(DND_FILES)
    source_folder_listbox.dnd_bind('<<Drop>>', on_source_drop)

source_buttons_frame = ttk.Frame(source_folder_frame)
source_buttons_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(5,0))
add_source_button = ttk.Button(source_buttons_frame, text="Add", command=add_source_folder)
add_source_button.pack(pady=2, fill=tk.X)
remove_source_button = ttk.Button(source_buttons_frame, text="Remove", command=remove_source_folder)
remove_source_button.pack(pady=2, fill=tk.X)


# --- 중간 프레임 (분석 버튼, 분류 모드 전환 버튼, 결과 트리뷰) ---
control_buttons_frame = ttk.Frame(middle_frame)
control_buttons_frame.pack(pady=10, fill=tk.X)

# 왼쪽 빈 공간
left_spacer = ttk.Frame(control_buttons_frame)
left_spacer.pack(side=tk.LEFT, expand=True)

# 스캔 버튼 (가운데 배치)
scan_button = ttk.Button(control_buttons_frame, text="2. Scan and Analyze JPG Files", command=scan_and_analyze_files)
scan_button.pack(side=tk.LEFT)

# 클리어 버튼 (스캔 버튼 옆에 배치)
clear_button = ttk.Button(control_buttons_frame, text="Clear Results", command=clear_analysis_results)
clear_button.pack(side=tk.LEFT, padx=(10, 0))

# 프로그레스바 (초기에는 숨김)
progress_bar = ttk.Progressbar(control_buttons_frame, mode='indeterminate')
# pack은 scan_and_analyze_files 함수에서 필요할 때만 수행

# 오른쪽 빈 공간
right_spacer = ttk.Frame(control_buttons_frame)
right_spacer.pack(side=tk.LEFT, expand=True)

# 정렬 모드 라디오 버튼 (우측 끝에 배치)
sort_frame = ttk.Frame(control_buttons_frame)
sort_frame.pack(side=tk.RIGHT, padx=10)

sort_label = ttk.Label(sort_frame, text="Sort by:")
sort_label.pack(side=tk.LEFT, padx=(0, 5))

sort_mode_var = tk.StringVar(value='count')  # 기본값은 Count

count_radio = ttk.Radiobutton(sort_frame, text="Count", variable=sort_mode_var, value='count', command=on_sort_mode_change)
count_radio.pack(side=tk.LEFT, padx=5)

name_radio = ttk.Radiobutton(sort_frame, text="Name", variable=sort_mode_var, value='name', command=on_sort_mode_change)
name_radio.pack(side=tk.LEFT, padx=5)

result_tree_frame = ttk.Frame(middle_frame)
result_tree_frame.pack(fill=tk.BOTH, expand=True)

result_tree = ttk.Treeview(result_tree_frame, columns=("filepath",), displaycolumns=(), selectmode='extended') # filepath 컬럼은 값 저장용, 화면엔 표시 안함
result_tree.heading("#0", text="Camera > Lens > Files", anchor=tk.W)

# 이벤트 바인딩
result_tree.bind("<Double-1>", on_tree_double_click)  # 더블클릭
result_tree.bind("<Button-3>", on_tree_right_click)   # 우클릭
result_tree.bind("<<TreeviewSelect>>", on_tree_single_click)  # 선택 변경 시

result_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

# Treeview 스크롤바
tree_scrollbar_y = ttk.Scrollbar(result_tree_frame, orient=tk.VERTICAL, command=result_tree.yview)
tree_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
result_tree.configure(yscrollcommand=tree_scrollbar_y.set)
tree_scrollbar_x = ttk.Scrollbar(middle_frame, orient=tk.HORIZONTAL, command=result_tree.xview) # 가로 스크롤바는 middle_frame에 직접 추가
tree_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
result_tree.configure(xscrollcommand=tree_scrollbar_x.set)


# --- 하단 프레임 (이미지 미리보기, 대상 폴더, 파일 처리 버튼) ---
# 하단 프레임을 가운데 정렬로 변경
bottom_center_frame = ttk.Frame(bottom_frame)
bottom_center_frame.pack(expand=True)

# 이미지 미리보기 섹션
preview_frame = ttk.LabelFrame(bottom_center_frame, text="Image Preview", padding="10")
preview_frame.pack(side=tk.LEFT, padx=10)

# 이미지 미리보기 라벨
preview_label = ttk.Label(preview_frame, text="", width=25, anchor=tk.CENTER)
preview_label.pack(pady=5)

# 파일명 라벨
filename_label = ttk.Label(preview_frame, text="Please select an image", wraplength=200, anchor=tk.CENTER, justify=tk.CENTER)
filename_label.pack(pady=(5, 45))

# Target folder section
target_folder_frame = ttk.LabelFrame(bottom_center_frame, text="3. Target Folder", padding="10")
target_folder_frame.pack(side=tk.LEFT, padx=10)

select_target_button = ttk.Button(target_folder_frame, text="Select Target Folder", command=select_target_folder)
select_target_button.pack(pady=5)
target_folder_label = ttk.Label(target_folder_frame, text="Target folder: Not selected", wraplength=200)
target_folder_label.pack(pady=5)

# 드래그 앤 드롭 바인딩 (대상 폴더)
if DND_AVAILABLE:
    target_folder_frame.drop_target_register(DND_FILES)
    target_folder_frame.dnd_bind('<<Drop>>', on_target_drop)
    # 라벨에도 드롭 가능하도록 설정
    target_folder_label.drop_target_register(DND_FILES)
    target_folder_label.dnd_bind('<<Drop>>', on_target_drop)

# File processing buttons
# Actions 섹션으로 Copy/Move 버튼 묶기
action_frame = ttk.LabelFrame(bottom_center_frame, text="4. Actions", padding="10")
action_frame.pack(side=tk.LEFT, padx=10)

copy_button = ttk.Button(action_frame, text="Copy Selected Files", command=lambda: process_files("copy"))
copy_button.pack(side=tk.TOP, pady=5)

move_button = ttk.Button(action_frame, text="Move Selected Files", command=lambda: process_files("move"))
move_button.pack(side=tk.TOP, pady=5)

# --- 상태 표시줄 ---
status_label = ttk.Label(status_frame, text="Ready", anchor=tk.W)
status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)


window.mainloop()