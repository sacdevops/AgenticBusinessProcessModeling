""" Agentic Process Modeling v.2 """
import io
import signal
import sys

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import config

app = Flask(__name__,
            template_folder='app/templates',
            static_folder='app/static')
app.config['SECRET_KEY'] = config.SECRET_KEY

socketio = SocketIO(
    app, 
    cors_allowed_origins="*",
    ping_timeout=300,
    ping_interval=25,
    async_mode='eventlet'
)

from app.sockets import chat_handler
chat_handler.register_handlers(socketio)

@app.route('/')
def index():
    return render_template('index.html', tasks=config.TASKS)

@app.route('/task/<task_id>')
def task_page(task_id):
    task = config.TASKS_BY_ID.get(task_id)
    if not task:
        return "Task not found", 404
    return render_template('task.html', task=task, is_custom=False)

@app.route('/task/custom')
def custom_task_page():
    task = {'id': 'custom', 'title': 'Custom Task', 'description': ''}
    return render_template('task.html', task=task, is_custom=True)


@app.route('/api/extract-file-content', methods=['POST'])
def extract_file_content():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file provided'}), 400

    file = request.files['file']
    filename = file.filename or ''
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    try:
        if ext in ('txt', 'md', 'csv'):
            content = file.read().decode('utf-8', errors='replace')
        elif ext == 'pdf':
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(file.read()))
            content = '\n'.join(page.extract_text() or '' for page in reader.pages)
        elif ext == 'docx':
            from docx import Document
            doc = Document(io.BytesIO(file.read()))
            content = '\n'.join(para.text for para in doc.paragraphs)
        else:
            return jsonify({'success': False, 'message': f'Unsupported file type: .{ext}'}), 400

        return jsonify({'success': True, 'content': content})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/save-bpmn', methods=['POST'])
def save_bpmn():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    task_id = data.get('task_id', '')
    bpmn_xml = data.get('bpmn_xml', '')

    if not bpmn_xml:
        return jsonify({'success': False, 'message': 'No BPMN XML provided'}), 400

    chat_handler.complete_and_upload(task_id, bpmn_xml)
    return jsonify({'success': True})


def _graceful_shutdown(signum, frame):
    """Graceful shutdown handler."""
    print(f'\n[Backend] Received signal {signum}, shutting down...')
    print('[Backend] Shutdown complete.')
    sys.exit(0)


signal.signal(signal.SIGINT, _graceful_shutdown)
signal.signal(signal.SIGTERM, _graceful_shutdown)

if __name__ == '__main__':
    socketio.run(
        app,
        debug=config.FLASK_DEBUG,
        host='127.0.0.1',
        port=8080
    )
