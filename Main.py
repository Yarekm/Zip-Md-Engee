#!/usr/bin/env python3
"""
КОНВЕРТЕР ZIP -> MD
Работает с ZIP файлами из папки models
"""

import os
import zipfile
import json
import requests
import time

# ================= НАСТРОЙКИ =================
INPUT_FOLDER = "models"                # Папка с ZIP файлами
OUTPUT_FOLDER = "./mds"                # Куда сохранять .md файлы
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "codellama:13b"            # Или другая модель

# Создаем папку для результатов
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ================= ПРОМПТ =================
SYSTEM_PROMPT = """Проанализируй приложенную модель блок-схемы для среды Engee (аналог MATLAB Simulink). 
Файл модели — это архив (zip) с JSON-файлами, описывающими блоки, параметры и связи. 
Основная схема находится в файле root.json. Подсистемы, если они есть, находятся в отдельных файлах с хешеподобными именами.

Твоя задача — составить краткое техническое описание модели (ТЗ) в формате Markdown. 
Описание должно быть достаточно подробным, чтобы по нему другой инженер или LLM могли воссоздать эквивалентную модель.

Требования к содержанию:
1. Кратко опиши назначение модели и ее роль в системе (1–3 предложения).
2. Опиши параметры моделирования, если они есть (тип решателя, шаг интегрирования, время моделирования и т.п.).
3. Перечисли используемые блоки с ключевыми параметрами:
    - источники сигналов (тип, имя, основные числовые параметры);
    - математические/логические блоки (тип, имя, важные коэффициенты, пороги, диапазоны);
    - приемники (sinks) и их роль.
4. Опиши логическую цепочку работы схемы:
    - как формируется входной сигнал(ы);
    - как он разветвляется и преобразуется;
    - как вычисляются ключевые выходы;
    - какие ограничения, насыщения, переключатели используются и по каким условиям.
5. Опиши структуру модели:
    - является ли модель плоской или содержит подсистемы;
    - для каждой подсистемы кратко опиши ее назначение и входы/выходы.

Требования к формату:
- Пиши только текст в Markdown, без таблиц и без исходного кода.
- Структурируй ответ заголовками второго уровня: "Общее описание модели", "Параметры симуляции", "Используемые блоки", "Логическая цепочка", "Структура модели".
- Не добавляй собственные предположения о физической системе, если это явно не следует из данных модели.
- Если какой-то информации в модели нет, явно напиши, что она отсутствует.

Выведи только итоговый текст ТЗ в Markdown без дополнительных комментариев."""

# ================= ФУНКЦИИ =================
def process_zip_file(zip_path):
    """Обрабатывает один ZIP файл и возвращает детальную информацию"""
    try:
        file_name = os.path.basename(zip_path)
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Читаем все JSON файлы
            json_files = {}
            for json_file in zf.namelist():
                if json_file.endswith('.json'):
                    try:
                        with zf.open(json_file) as f:
                            json_files[json_file] = json.load(f)
                    except:
                        json_files[json_file] = None
            
            # Собираем детальную информацию
            analysis = {
                'filename': file_name,
                'json_count': len(json_files),
                'model_name': 'Неизвестно',
                'model_type': 'Неизвестно',
                'simulation_params': {},
                'blocks': [],
                'sources': [],
                'math_blocks': [],
                'sinks': [],
                'subsystems': [],
                'lines': []
            }
            
            # 1. Извлекаем основную информацию о модели
            if 'model.json' in json_files and json_files['model.json']:
                model = json_files['model.json']
                analysis['model_name'] = model.get('name', 'Неизвестно')
                analysis['model_type'] = model.get('type', 'Неизвестно')
            
            # 2. Извлекаем параметры симуляции
            if 'configset.json' in json_files and json_files['configset.json']:
                config = json_files['configset.json']
                if 'sets' in config and 'Configuration' in config['sets']:
                    solver = config['sets']['Configuration'].get('Components', {}).get('Solver', {})
                    analysis['simulation_params'] = {
                        'StartTime': solver.get('StartTime'),
                        'StopTime': solver.get('StopTime'),
                        'SolverType': solver.get('SolverType'),
                        'SolverName': solver.get('SolverName'),
                        'FixedStep': solver.get('FixedStep')
                    }
            
            # 3. Анализируем блоки из root.json
            if 'root.json' in json_files and json_files['root.json']:
                root = json_files['root.json']
                if 'objects' in root:
                    objects = root['objects']
                    
                    # Собираем все блоки
                    for obj_id, obj in objects.items():
                        if obj.get('type') == 'block':
                            block_info = {
                                'id': obj_id,
                                'name': obj.get('blockName', f'block_{obj_id[:8]}'),
                                'type': obj.get('blockType', 'Unknown'),
                                'path': obj.get('blockPath', ''),
                                'values': obj.get('blockValues', {})
                            }
                            analysis['blocks'].append(block_info)
                            
                            # Категоризируем блоки
                            block_path = block_info['path'].lower()
                            if 'source' in block_path:
                                analysis['sources'].append(block_info)
                            elif 'sink' in block_path:
                                analysis['sinks'].append(block_info)
                            elif any(x in block_path for x in ['math', 'operation', 'switch', 'saturation', 'gain', 'logic']):
                                analysis['math_blocks'].append(block_info)
                        
                        elif obj.get('type') == 'line':
                            line_info = {
                                'id': obj_id,
                                'source': obj.get('source', {}),
                                'destination': obj.get('destination', {}),
                                'title': obj.get('view', {}).get('line', {}).get('title', '')
                            }
                            analysis['lines'].append(line_info)
            
            # 4. Ищем подсистемы
            for json_file, content in json_files.items():
                if (json_file not in ['model.json', 'root.json', 'configset.json', 'storage.json', 'callbacks.json'] and 
                    content and isinstance(content, dict) and 'objects' in content):
                    # Это похоже на подсистему
                    analysis['subsystems'].append(json_file)
            
            return {
                'success': True,
                'analysis': analysis,
                'error': None
            }
            
    except Exception as e:
        return {
            'success': False,
            'analysis': None,
            'error': str(e)
        }

def prepare_prompt_from_analysis(analysis):
    """Подготавливает данные для промпта на основе анализа"""
    parts = []
    
    # Основная информация
    parts.append(f"Имя файла модели: {analysis['filename']}")
    parts.append(f"Имя модели: {analysis['model_name']}")
    parts.append(f"Тип модели: {analysis['model_type']}")
    parts.append(f"Всего JSON файлов: {analysis['json_count']}")
    
    # Параметры симуляции
    parts.append("\nПАРАМЕТРЫ СИМУЛЯЦИИ:")
    if analysis['simulation_params']:
        for key, value in analysis['simulation_params'].items():
            if value:
                parts.append(f"  {key}: {value}")
    else:
        parts.append("  Не указаны в файле модели")
    
    # Источники сигналов
    parts.append(f"\nИСТОЧНИКИ СИГНАЛОВ ({len(analysis['sources'])}):")
    for source in analysis['sources'][:10]:
        params = []
        for key, value in source['values'].items():
            if isinstance(value, (str, int, float)) and str(value).strip():
                params.append(f"{key}={value}")
        param_str = f" ({', '.join(params)})" if params else ""
        parts.append(f"  • {source['name']} ({source['type']}){param_str}")
    
    # Математические блоки
    parts.append(f"\nМАТЕМАТИЧЕСКИЕ/ЛОГИЧЕСКИЕ БЛОКИ ({len(analysis['math_blocks'])}):")
    for block in analysis['math_blocks'][:15]:  # Ограничиваем 15 блоками
        params = []
        for key, value in block['values'].items():
            if isinstance(value, (str, int, float)) and str(value).strip():
                params.append(f"{key}={value}")
        param_str = f" ({', '.join(params[:3])})" if params else ""  # Первые 3 параметра
        parts.append(f"  • {block['name']} ({block['type']}){param_str}")
    
    # Приемники
    parts.append(f"\nПРИЕМНИКИ (SINKS) ({len(analysis['sinks'])}):")
    for sink in analysis['sinks'][:10]:
        parts.append(f"  • {sink['name']} ({sink['type']})")
    
    # Подсистемы
    parts.append(f"\nПОДСИСТЕМЫ ({len(analysis['subsystems'])}):")
    if analysis['subsystems']:
        for i, subsystem in enumerate(analysis['subsystems'][:10], 1):
            parts.append(f"  {i}. {subsystem}")
        if len(analysis['subsystems']) > 10:
            parts.append(f"  ... и еще {len(analysis['subsystems']) - 10} подсистем")
    else:
        parts.append("  Подсистемы не обнаружены (плоская модель)")
    
    # Статистика связей
    parts.append(f"\nСТАТИСТИКА:")
    parts.append(f"  Всего блоков: {len(analysis['blocks'])}")
    parts.append(f"  Всего связей: {len(analysis['lines'])}")
    
    return "\n".join(parts)

def ask_ollama(prompt_text):
    """Запрос к локальной модели"""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt_text,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 5000
                }
            },
            timeout=120  # 2 минуты
        )
        
        if response.status_code == 200:
            return response.json().get("response", "")
        else:
            return f"Ошибка API: {response.status_code}"
            
    except requests.exceptions.ConnectionError:
        return "Ошибка: Не могу подключиться к Ollama. Запустите: ollama serve"
    except Exception as e:
        return f"Ошибка: {str(e)}"

def save_md(zip_name, content):
    """Сохраняет MD файл"""
    # Берем только имя файла без пути
    base_name = os.path.basename(zip_name)
    md_name = base_name.replace('.zip', '.md').replace('.ZIP', '.md')
    if not md_name.endswith('.md'):
        md_name += '.md'
    
    output_path = os.path.join(OUTPUT_FOLDER, md_name)
    
    with open(output_path, 'w', encoding='utf-8', errors='ignore') as f:
        f.write(content)
    
    return output_path

# ================= ОСНОВНАЯ ЧАСТЬ =================
print("=" * 70)
print("КОНВЕРТЕР ZIP -> MD")
print("=" * 70)

# Проверяем Ollama
try:
    test = requests.get("http://localhost:11434/api/tags", timeout=5)
    if test.status_code == 200:
        print(f" Ollama доступен, модель: {OLLAMA_MODEL}")
        use_ai = True
    else:
        print(f"  Ollama отвечает с ошибкой {test.status_code}")
        use_ai = False
except:
    print("✗ Ollama недоступен. Будут созданы только сырые данные.")
    use_ai = False

# Проверяем папку models
if not os.path.exists(INPUT_FOLDER):
    print(f"\n Папка '{INPUT_FOLDER}' не существует!")
    print("Создайте папку 'models' и положите туда ZIP файлы")
    exit(1)

# Ищем ZIP файлы
zip_files = [f for f in os.listdir(INPUT_FOLDER) 
            if f.lower().endswith(('.zip', '.engee'))]

if not zip_files:
    print(f"\n Нет ZIP файлов в папке '{INPUT_FOLDER}'!")
    exit(1)

print(f"\nНайдено файлов: {len(zip_files)}")

# Обрабатываем каждый файл
success_count = 0
errors = 0

for i, zip_file in enumerate(zip_files, 1):
    print(f"\n[{i}/{len(zip_files)}] Обрабатываю: {zip_file}")
    
    full_path = os.path.join(INPUT_FOLDER, zip_file)
    
    # 1. Анализируем ZIP файл
    result = process_zip_file(full_path)
    
    if not result['success']:
        print(f"   Ошибка анализа: {result['error']}")
        error_content = f"# Ошибка обработки файла: {zip_file}\n\n**Ошибка:** {result['error']}"
        save_md(zip_file, error_content)
        errors += 1
        continue
    
    analysis = result['analysis']
    print(f"  ✓ Блоков: {len(analysis['blocks'])}, Связей: {len(analysis['lines'])}")
    
    # 2. Подготавливаем данные для промпта
    model_data = prepare_prompt_from_analysis(analysis)
    
    # 3. Формируем финальный промпт
    final_prompt = f"{SYSTEM_PROMPT}\n\n---\n\nДАННЫЕ МОДЕЛИ:\n\n{model_data}\n\n---\n\nНАЧИНАЙ ВЫВОД СРАЗУ С ЗАГОЛОВКА 'Общее описание модели':"
    
    # 4. Получаем описание от ИИ
    if use_ai:
        print("  Генерирую описание с помощью ИИ...")
        description = ask_ollama(final_prompt)
        
        # Проверяем на ошибки
        if "Ошибка" in description or "ошибка" in description.lower():
            print(f"  Проблема с ИИ: {description[:80]}...")
            # Используем сырые данные
            description = f"# Модель: {analysis['model_name']}\n\n## Общее описание модели\n\nНе удалось сгенерировать описание с помощью ИИ.\n\n## Данные модели:\n\n```\n{model_data}\n```"
    else:
        print("  Создаю сырое описание...")
        description = f"# Модель: {analysis['model_name']}\n\n## Общее описание модели\n\nОбработка через ИИ недоступна.\n\n## Данные модели:\n\n```\n{model_data}\n```"
    
    # 5. Добавляем метаданные
    final_content = f"""# Техническое описание модели

**Исходный файл:** `{zip_file}`
**Имя модели:** {analysis['model_name']}
**Дата генерации:** {time.strftime('%Y-%m-%d %H:%M:%S')}
**Модель ИИ:** {OLLAMA_MODEL if use_ai else 'Не использовалась'}

---

{description}
"""
    
    # 6. Сохраняем
    try:
        md_path = save_md(zip_file, final_content)
        print(f"  ✓ Сохранено: {os.path.basename(md_path)}")
        success_count += 1
    except Exception as e:
        print(f" Ошибка сохранения: {e}")
        errors += 1
    
    # Пауза между файлами
    if i < len(zip_files):
        time.sleep(1)

print("\n" + "=" * 70)
print("ОБРАБОТКА ЗАВЕРШЕНА!")
print("=" * 70)
print(f"Всего файлов: {len(zip_files)}")
print(f"Успешно обработано: {success_count}")
print(f"С ошибками: {errors}")
print(f"\nРезультаты сохранены в: {os.path.abspath(OUTPUT_FOLDER)}")

# Создаем индексный файл
index_path = os.path.join(OUTPUT_FOLDER, "INDEX.md")
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(f"""# Индекс обработанных моделей

Дата обработки: {time.strftime('%Y-%m-%d %H:%M:%S')}
Всего моделей: {len(zip_files)}
Успешно: {success_count}
С ошибками: {errors}
Модель ИИ: {OLLAMA_MODEL if use_ai else 'Не использовалась'}

## Список файлов:

""")
    
    for zip_file in sorted(zip_files):
        md_name = zip_file.replace('.zip', '.md').replace('.ZIP', '.md')
        if not md_name.endswith('.md'):
            md_name += '.md'
        
        if os.path.exists(os.path.join(OUTPUT_FOLDER, md_name)):
            f.write(f" [{zip_file}]({md_name})\n")
        else:
            f.write(f" {zip_file}\n")

print(f"\nСоздан индексный файл: INDEX.md")
print("\n" + "=" * 70)

if os.name == 'nt':
    input("\nНажмите Enter для выхода...")