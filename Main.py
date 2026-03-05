"""
КОНВЕРТЕР МОДЕЛЕЙ ENGEE -> MD
"""

import os
import zipfile
import json
import requests
import time

# Конфигурация
INPUT_FOLDER = "models"
OUTPUT_FOLDER = "./mds_deepseek"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "deepseek/deepseek-chat"

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

SYSTEM_PROMPT = """Анализируй модель Engee. Создай техническое описание в Markdown:

1. Общее описание модели по именам блоков и сигналов
2. Используемые блоки с ключевыми параметрами
3. Логическая цепочка работы - как сигналы проходят через блоки
4. Структура модели и назначение подсистем

Формат:
- Только Markdown
- Заголовки: "Общее описание", "Используемые блоки", "Логическая цепочка", "Структура модели"

Только текст ТЗ в Markdown."""

def get_api_key():
    """Получает API ключ"""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        return api_key
    
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if line.strip().startswith("OPENROUTER_API_KEY="):
                    return line.split("=", 1)[1].strip()
    
    return None

def analyze_file(zf, filename):
    """Анализирует файл модели"""
    try:
        with zf.open(filename) as f:
            data = json.load(f)
        
        # Ищем объекты
        objects = None
        if 'objects' in data:
            objects = data['objects']
        elif 'state' in data and 'objects' in data['state']:
            objects = data['state']['objects']
        
        if not objects:
            return [], []
        
        blocks = []
        lines = []
        
        for obj_id, obj in objects.items():
            if obj.get('type') == 'block':
                blocks.append({
                    'id': obj_id[:8],
                    'name': obj.get('blockName', f'Block_{obj_id[:8]}'),
                    'type': obj.get('blockType', '')
                })
            elif obj.get('type') == 'line':
                lines.append({
                    'from': obj.get('source', {}).get('block_id', '')[:8],
                    'to': obj.get('destination', {}).get('block_id', '')[:8]
                })
        
        return blocks, lines
        
    except:
        return [], []

def extract_model_data(zip_path):
    """Извлекает данные из ZIP файла"""
    try:
        file_name = os.path.basename(zip_path)
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            all_files = zf.namelist()
            
            analysis = {
                'filename': file_name,
                'model_name': file_name.replace('.zip', '').replace('.engee', ''),
                'root_blocks': [],
                'root_lines': [],
                'subsystems': [],
                'total_blocks': 0
            }
            
            # model.json
            if 'model.json' in all_files:
                try:
                    with zf.open('model.json') as f:
                        model_data = json.load(f)
                        name = model_data.get('name', '')
                        if name:
                            analysis['model_name'] = name
                except:
                    pass
            
            # root.json
            if 'root.json' in all_files:
                blocks, lines = analyze_file(zf, 'root.json')
                analysis['root_blocks'] = blocks
                analysis['root_lines'] = lines
                analysis['total_blocks'] += len(blocks)
            
            # Подсистемы
            for file in all_files:
                if (file.endswith('.json') and 
                    file not in ['model.json', 'configset.json', 'root.json'] and
                    'model_inference' not in file):
                    
                    blocks, lines = analyze_file(zf, file)
                    
                    if blocks:
                        analysis['subsystems'].append({
                            'filename': file,
                            'blocks': blocks[:20],
                            'lines': lines[:20],
                            'block_count': len(blocks)
                        })
                        analysis['total_blocks'] += len(blocks)
            
            return True, analysis, ""
            
    except Exception as e:
        return False, {}, f"Ошибка: {str(e)}"

def prepare_data_for_prompt(analysis):
    """Готовит данные для промпта"""
    parts = []
    
    parts.append(f"Модель: {analysis['model_name']}")
    parts.append(f"Файл: {analysis['filename']}")
    
    parts.append(f"\nСтатистика:")
    parts.append(f"Всего блоков: {analysis['total_blocks']}")
    parts.append(f"Подсистем: {len(analysis['subsystems'])}")
    
    # Блоки в root.json
    if analysis['root_blocks']:
        parts.append(f"\nБлоки в основной схеме:")
        for block in analysis['root_blocks'][:10]:
            parts.append(f"- {block['name']} ({block['type']})")
    
    # Подсистемы
    if analysis['subsystems']:
        parts.append(f"\nПодсистемы:")
        for subsystem in analysis['subsystems']:
            parts.append(f"\n{subsystem['filename']}:")
            parts.append(f"  Блоков: {subsystem['block_count']}")
            
            if subsystem['blocks']:
                parts.append(f"  Примеры блоков:")
                for block in subsystem['blocks'][:3]:
                    parts.append(f"  - {block['name']} ({block['type']})")
    
    return "\n".join(parts)

def ask_ai(api_key, prompt_text):
    """Отправляет запрос к ИИ"""
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_text}
            ],
            "temperature": 0.1,
            "max_tokens": 2000
        }
        
        response = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                return True, result['choices'][0]['message']['content'], ""
        
        return False, "", f"Ошибка API: {response.status_code}"
            
    except Exception as e:
        return False, "", f"Ошибка: {str(e)}"

def save_md(zip_filename, content):
    """Сохраняет Markdown файл"""
    base_name = os.path.basename(zip_filename)
    if base_name.lower().endswith('.zip'):
        md_name = base_name[:-4] + '.md'
    else:
        md_name = base_name + '.md'
    
    output_path = os.path.join(OUTPUT_FOLDER, md_name)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return output_path

def main():
    print("=" * 60)
    print("АНАЛИЗ МОДЕЛЕЙ ENGEE")
    print("=" * 60)
    
    api_key = get_api_key()
    if not api_key:
        print("Требуется API ключ")
        return
    
    print(f"Модель ИИ: {MODEL}")
    print(f"Папка с моделями: {INPUT_FOLDER}")
    
    if not os.path.exists(INPUT_FOLDER):
        print(f"Папка '{INPUT_FOLDER}' не существует!")
        return
    
    zip_files = sorted([f for f in os.listdir(INPUT_FOLDER) 
                       if f.lower().endswith(('.zip', '.engee'))])
    
    if not zip_files:
        print("Нет файлов моделей!")
        return
    
    # Проверяем обработанные файлы
    processed = set()
    for file in os.listdir(OUTPUT_FOLDER):
        if file.endswith('.md'):
            zip_name = file[:-3] + '.zip'
            if zip_name in zip_files:
                processed.add(zip_name)
    
    files_to_process = [f for f in zip_files if f not in processed]
    
    print(f"\nВсего моделей: {len(zip_files)}")
    print(f"Уже обработано: {len(processed)}")
    print(f"Осталось: {len(files_to_process)}")
    
    if not files_to_process:
        print("Все модели уже обработаны!")
        return
    
    processed_count = 0
    error_count = 0
    
    for i, zip_file in enumerate(files_to_process, 1):
        print(f"\n[{i}/{len(files_to_process)}] {zip_file}")
        
        full_path = os.path.join(INPUT_FOLDER, zip_file)
        
        try:
            success, analysis, error = extract_model_data(full_path)
        except Exception as e:
            print(f"  Ошибка извлечения: {e}")
            error_count += 1
            continue
        
        if not success:
            print(f"  Ошибка: {error}")
            error_count += 1
            continue
        
        print(f"  Блоков: {analysis['total_blocks']}")
        print(f"  Подсистем: {len(analysis['subsystems'])}")
        
        # Готовим данные для ИИ
        model_data = prepare_data_for_prompt(analysis)
        
        # Отправляем запрос
        ai_success, ai_description, ai_error = ask_ai(api_key, model_data)
        
        # Создаем документ
        if ai_success:
            content = f"""# Техническое описание модели Engee

**Файл:** {zip_file}
**Модель:** {analysis['model_name']}
**Дата:** {time.strftime('%Y-%m-%d %H:%M:%S')}

---

{ai_description}

---

*Сгенерировано автоматически.*
"""
        else:
            content = f"""# Техническое описание модели Engee

**Файл:** {zip_file}
**Модель:** {analysis['model_name']}
**Дата:** {time.strftime('%Y-%m-%d %H:%M:%S')}
**Ошибка:** {ai_error}

## Статистика
- Всего блоков: {analysis['total_blocks']}
- Подсистем: {len(analysis['subsystems'])}"""
            
            if analysis['root_blocks']:
                content += f"\n\n## Блоки в основной схеме"
                for block in analysis['root_blocks'][:10]:
                    content += f"\n- {block['name']} ({block['type']})"
            
            if analysis['subsystems']:
                content += f"\n\n## Подсистемы"
                for subsystem in analysis['subsystems']:
                    content += f"\n\n### {subsystem['filename']}"
                    content += f"\n- Блоков: {subsystem['block_count']}"
                    if subsystem['blocks']:
                        for block in subsystem['blocks'][:5]:
                            content += f"\n- {block['name']} ({block['type']})"
        
        # Сохраняем
        try:
            save_md(zip_file, content)
            print(f"  Сохранено")
            processed_count += 1
        except Exception as e:
            print(f"  Ошибка сохранения: {e}")
            error_count += 1
        
        # Пауза
        if i < len(files_to_process):
            time.sleep(2)
    
    print(f"\n" + "=" * 60)
    print(f"ОБРАБОТКА ЗАВЕРШЕНА")
    print(f"=" * 60)
    print(f"Обработано: {processed_count}")
    print(f"Ошибок: {error_count}")
    print(f"Всего: {len(processed) + processed_count}/{len(zip_files)}")
    print(f"\nРезультаты в: {os.path.abspath(OUTPUT_FOLDER)}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nПрервано")
    except Exception as e:
        print(f"Ошибка: {e}")
