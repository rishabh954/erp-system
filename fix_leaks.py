import os
import re


# Find all files with "error": str(e) or similar, add import logging if missing, and replace with logger.error
def process_file(file_path):
    with open(file_path, encoding='utf-8') as f:
        content = f.read()

    # If nothing to fix, return
    if 'str(e)' not in content and 'traceback.format_exc()' not in content:
        return False

    modified = False

    # 1. Add logging import at the top
    if 'import logging' not in content:
        if 'import os' in content:
            content = content.replace('import os', 'import os\nimport logging')
        elif 'import json' in content:
            content = content.replace('import json', 'import json\nimport logging')
        else:
            content = 'import logging\n' + content
        modified = True

    if 'logger = logging.getLogger(__name__)' not in content:
        # Find first class or def
        match = re.search(r'^(class |def |@)', content, re.MULTILINE)
        if match:
            content = content[:match.start()] + 'logger = logging.getLogger(__name__)\n\n\n' + content[match.start():]
            modified = True

    # Fix tracebacks and str(e) in HTTP responses
    # Pattern for JSON responses: "error": str(e) or 'error': str(e)
    # Pattern for sales traceback: "detail": traceback.format_exc()

    # We will search for 'except Exception as e:' blocks
    # and replace the content inside.
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'except Exception as e:' in line:
            # Check the next lines for str(e) or traceback
            for j in range(i+1, min(i+20, len(lines))):
                if 'except ' in lines[j] or 'def ' in lines[j] or 'class ' in lines[j]:
                    break

                if 'str(e)' in lines[j] and ('error' in lines[j].lower() or 'message' in lines[j].lower() or 'detail' in lines[j].lower()):
                    if 'logger.error' not in '\n'.join(lines[i:j]):
                        indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
                        lines.insert(j, indent + 'logger.error(f"Unexpected error: {str(e)}", exc_info=True)')
                        lines[j+1] = lines[j+1].replace('str(e)', '"An unexpected error occurred."')
                    else:
                        lines[j] = lines[j].replace('str(e)', '"An unexpected error occurred."')
                    modified = True
                    break

                if 'traceback.format_exc()' in lines[j] and ('error' in lines[j].lower() or 'message' in lines[j].lower() or 'detail' in lines[j].lower()):
                    if 'logger.error' not in '\n'.join(lines[i:j]):
                        indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
                        lines.insert(j, indent + 'logger.error("Unexpected error", exc_info=True)')
                        lines[j+1] = lines[j+1].replace('traceback.format_exc()', '"An unexpected error occurred."')
                    else:
                        lines[j] = lines[j].replace('traceback.format_exc()', '"An unexpected error occurred."')
                    modified = True
                    break

    if modified:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"Fixed {file_path}")
        return True
    return False

for root, _, files in os.walk('apps'):
    for file in files:
        if file.endswith('.py') and not file.startswith('test_'):
            process_file(os.path.join(root, file))
