"""
Servidor de Assinaturas Digitais - HAMI ERP
Deploy: Render.com
"""

import os
import json
import hashlib
import base64
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)
CORS(app)

# Configuração do banco de dados PostgreSQL (Render fornece automaticamente)
DATABASE_URL = os.environ.get('DATABASE_URL', '')

def get_db():
    """Retorna conexão com o banco de dados"""
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return conn

def init_db():
    """Inicializa tabelas do banco de dados"""
    conn = get_db()
    cur = conn.cursor()
    
    # Tabela de documentos
    cur.execute('''
        CREATE TABLE IF NOT EXISTS documentos (
            id SERIAL PRIMARY KEY,
            doc_id VARCHAR(64) UNIQUE NOT NULL,
            titulo VARCHAR(255),
            arquivo_nome VARCHAR(255),
            arquivo_base64 TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            criado_por VARCHAR(100)
        )
    ''')
    
    # Tabela de signatários
    cur.execute('''
        CREATE TABLE IF NOT EXISTS signatarios (
            id SERIAL PRIMARY KEY,
            doc_id VARCHAR(64) REFERENCES documentos(doc_id),
            nome VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            cpf VARCHAR(14),
            token VARCHAR(64) UNIQUE NOT NULL,
            assinado BOOLEAN DEFAULT FALSE,
            assinatura_base64 TEXT,
            ip_assinatura VARCHAR(45),
            data_assinatura TIMESTAMP,
            user_agent TEXT
        )
    ''')
    
    conn.commit()
    cur.close()
    conn.close()

# Inicializar banco ao iniciar
try:
    init_db()
except:
    pass  # Banco será inicializado na primeira requisição

# ==================== PÁGINAS HTML ====================

PAGINA_ASSINATURA = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Assinar Documento - HAMI ERP</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
            padding: 20px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            padding: 30px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
        }
        h1 {
            text-align: center;
            margin-bottom: 10px;
            color: #4fc3f7;
        }
        .info {
            background: rgba(79, 195, 247, 0.1);
            padding: 15px;
            border-radius: 10px;
            margin: 20px 0;
            border-left: 4px solid #4fc3f7;
        }
        .info p { margin: 5px 0; }
        .documento-frame {
            background: #fff;
            border-radius: 10px;
            padding: 10px;
            margin: 20px 0;
        }
        .documento-frame iframe {
            width: 100%;
            height: 400px;
            border: none;
            border-radius: 5px;
        }
        .assinatura-area {
            background: rgba(255,255,255,0.1);
            border-radius: 10px;
            padding: 20px;
            margin: 20px 0;
        }
        .assinatura-area h3 {
            margin-bottom: 15px;
            color: #4fc3f7;
        }
        #canvas-assinatura {
            background: #fff;
            border-radius: 10px;
            cursor: crosshair;
            touch-action: none;
            width: 100%;
            height: 200px;
        }
        .botoes {
            display: flex;
            gap: 10px;
            margin-top: 15px;
            flex-wrap: wrap;
        }
        .btn {
            padding: 12px 25px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.3s;
            flex: 1;
            min-width: 120px;
        }
        .btn-limpar {
            background: #666;
            color: #fff;
        }
        .btn-limpar:hover { background: #555; }
        .btn-assinar {
            background: linear-gradient(135deg, #4fc3f7 0%, #2196f3 100%);
            color: #fff;
        }
        .btn-assinar:hover { transform: translateY(-2px); box-shadow: 0 5px 20px rgba(79, 195, 247, 0.4); }
        .btn-assinar:disabled { background: #666; cursor: not-allowed; transform: none; }
        .sucesso {
            background: rgba(76, 175, 80, 0.2);
            border: 2px solid #4caf50;
            border-radius: 15px;
            padding: 30px;
            text-align: center;
            margin: 20px 0;
        }
        .sucesso h2 { color: #4caf50; margin-bottom: 10px; }
        .erro {
            background: rgba(244, 67, 54, 0.2);
            border: 2px solid #f44336;
            border-radius: 15px;
            padding: 30px;
            text-align: center;
        }
        .erro h2 { color: #f44336; }
        .ja-assinado {
            background: rgba(255, 193, 7, 0.2);
            border: 2px solid #ffc107;
            border-radius: 15px;
            padding: 30px;
            text-align: center;
        }
        .ja-assinado h2 { color: #ffc107; }
        @media (max-width: 600px) {
            .container { padding: 15px; }
            .botoes { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📝 Assinatura Digital</h1>
        <p style="text-align: center; color: #aaa;">HAMI ERP - Sistema de Assinaturas</p>
        
        <div id="conteudo">
            <!-- Conteúdo será carregado via JavaScript -->
            <p style="text-align: center; padding: 50px;">Carregando...</p>
        </div>
    </div>

    <script>
        const token = '{{ token }}';
        let canvas, ctx;
        let desenhando = false;
        let temAssinatura = false;

        async function carregarDocumento() {
            try {
                const resp = await fetch(`/api/documento/${token}`);
                const data = await resp.json();
                
                if (data.erro) {
                    document.getElementById('conteudo').innerHTML = `
                        <div class="erro">
                            <h2>❌ Erro</h2>
                            <p>${data.erro}</p>
                        </div>
                    `;
                    return;
                }
                
                if (data.ja_assinado) {
                    document.getElementById('conteudo').innerHTML = `
                        <div class="ja-assinado">
                            <h2>✅ Documento Já Assinado</h2>
                            <p>Este documento foi assinado em ${data.data_assinatura}</p>
                        </div>
                    `;
                    return;
                }
                
                document.getElementById('conteudo').innerHTML = `
                    <div class="info">
                        <p><strong>📄 Documento:</strong> ${data.titulo || data.arquivo_nome}</p>
                        <p><strong>👤 Signatário:</strong> ${data.signatario_nome}</p>
                        <p><strong>📧 Email:</strong> ${data.signatario_email || 'Não informado'}</p>
                    </div>
                    
                    <div class="documento-frame">
                        <iframe src="/api/pdf/${token}" title="Documento PDF"></iframe>
                    </div>
                    
                    <div class="assinatura-area">
                        <h3>✍️ Desenhe sua assinatura abaixo:</h3>
                        <canvas id="canvas-assinatura"></canvas>
                        <div class="botoes">
                            <button class="btn btn-limpar" onclick="limparAssinatura()">🗑️ Limpar</button>
                            <button class="btn btn-assinar" id="btn-assinar" onclick="enviarAssinatura()" disabled>
                                ✅ Assinar Documento
                            </button>
                        </div>
                    </div>
                `;
                
                inicializarCanvas();
                
            } catch (e) {
                document.getElementById('conteudo').innerHTML = `
                    <div class="erro">
                        <h2>❌ Erro de Conexão</h2>
                        <p>Não foi possível carregar o documento. Tente novamente.</p>
                    </div>
                `;
            }
        }

        function inicializarCanvas() {
            canvas = document.getElementById('canvas-assinatura');
            ctx = canvas.getContext('2d');
            
            // Ajustar tamanho real do canvas
            const rect = canvas.getBoundingClientRect();
            canvas.width = rect.width;
            canvas.height = 200;
            
            ctx.strokeStyle = '#000';
            ctx.lineWidth = 2;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            
            // Eventos mouse
            canvas.addEventListener('mousedown', iniciarDesenho);
            canvas.addEventListener('mousemove', desenhar);
            canvas.addEventListener('mouseup', pararDesenho);
            canvas.addEventListener('mouseout', pararDesenho);
            
            // Eventos touch
            canvas.addEventListener('touchstart', iniciarDesenhoTouch);
            canvas.addEventListener('touchmove', desenharTouch);
            canvas.addEventListener('touchend', pararDesenho);
        }

        function getPos(e) {
            const rect = canvas.getBoundingClientRect();
            return {
                x: e.clientX - rect.left,
                y: e.clientY - rect.top
            };
        }

        function getTouchPos(e) {
            const rect = canvas.getBoundingClientRect();
            const touch = e.touches[0];
            return {
                x: touch.clientX - rect.left,
                y: touch.clientY - rect.top
            };
        }

        function iniciarDesenho(e) {
            desenhando = true;
            const pos = getPos(e);
            ctx.beginPath();
            ctx.moveTo(pos.x, pos.y);
        }

        function iniciarDesenhoTouch(e) {
            e.preventDefault();
            desenhando = true;
            const pos = getTouchPos(e);
            ctx.beginPath();
            ctx.moveTo(pos.x, pos.y);
        }

        function desenhar(e) {
            if (!desenhando) return;
            const pos = getPos(e);
            ctx.lineTo(pos.x, pos.y);
            ctx.stroke();
            temAssinatura = true;
            document.getElementById('btn-assinar').disabled = false;
        }

        function desenharTouch(e) {
            if (!desenhando) return;
            e.preventDefault();
            const pos = getTouchPos(e);
            ctx.lineTo(pos.x, pos.y);
            ctx.stroke();
            temAssinatura = true;
            document.getElementById('btn-assinar').disabled = false;
        }

        function pararDesenho() {
            desenhando = false;
        }

        function limparAssinatura() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            temAssinatura = false;
            document.getElementById('btn-assinar').disabled = true;
        }

        async function enviarAssinatura() {
            if (!temAssinatura) {
                alert('Por favor, desenhe sua assinatura antes de confirmar.');
                return;
            }
            
            const btn = document.getElementById('btn-assinar');
            btn.disabled = true;
            btn.textContent = '⏳ Processando...';
            
            try {
                const assinaturaBase64 = canvas.toDataURL('image/png');
                
                const resp = await fetch('/api/assinar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        token: token,
                        assinatura: assinaturaBase64
                    })
                });
                
                const data = await resp.json();
                
                if (data.sucesso) {
                    document.getElementById('conteudo').innerHTML = `
                        <div class="sucesso">
                            <h2>✅ Documento Assinado com Sucesso!</h2>
                            <p>Sua assinatura foi registrada em ${new Date().toLocaleString('pt-BR')}</p>
                            <p style="margin-top: 15px; color: #aaa;">Você pode fechar esta página.</p>
                        </div>
                    `;
                } else {
                    alert('Erro ao assinar: ' + (data.erro || 'Erro desconhecido'));
                    btn.disabled = false;
                    btn.textContent = '✅ Assinar Documento';
                }
                
            } catch (e) {
                alert('Erro de conexão. Tente novamente.');
                btn.disabled = false;
                btn.textContent = '✅ Assinar Documento';
            }
        }

        // Carregar documento ao iniciar
        carregarDocumento();
    </script>
</body>
</html>
'''

PAGINA_INICIO = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HAMI ERP - Servidor de Assinaturas</title>
    <style>
        body {
            font-family: 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #fff;
        }
        .container {
            text-align: center;
            padding: 40px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            backdrop-filter: blur(10px);
        }
        h1 { color: #4fc3f7; margin-bottom: 10px; }
        p { color: #aaa; }
        .status { color: #4caf50; font-size: 24px; margin: 20px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📝 HAMI ERP</h1>
        <p>Servidor de Assinaturas Digitais</p>
        <div class="status">✅ Online</div>
        <p>Sistema funcionando corretamente.</p>
    </div>
</body>
</html>
'''

# ==================== ROTAS ====================

@app.route('/')
def index():
    """Página inicial"""
    return render_template_string(PAGINA_INICIO)

@app.route('/health')
def health():
    """Health check para Render"""
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

@app.route('/assinar/<token>')
def pagina_assinatura(token):
    """Página de assinatura para o signatário"""
    return render_template_string(PAGINA_ASSINATURA, token=token)

@app.route('/api/documento/<token>')
def get_documento(token):
    """Retorna informações do documento para assinatura"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT d.titulo, d.arquivo_nome, s.nome as signatario_nome, 
                   s.email as signatario_email, s.assinado, s.data_assinatura
            FROM signatarios s
            JOIN documentos d ON s.doc_id = d.doc_id
            WHERE s.token = %s
        ''', (token,))
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if not row:
            return jsonify({'erro': 'Token inválido ou documento não encontrado'})
        
        if row['assinado']:
            return jsonify({
                'ja_assinado': True,
                'data_assinatura': row['data_assinatura'].strftime('%d/%m/%Y às %H:%M') if row['data_assinatura'] else ''
            })
        
        return jsonify({
            'titulo': row['titulo'],
            'arquivo_nome': row['arquivo_nome'],
            'signatario_nome': row['signatario_nome'],
            'signatario_email': row['signatario_email'],
            'ja_assinado': False
        })
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/pdf/<token>')
def get_pdf(token):
    """Retorna o PDF do documento"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT d.arquivo_base64, d.arquivo_nome
            FROM signatarios s
            JOIN documentos d ON s.doc_id = d.doc_id
            WHERE s.token = %s
        ''', (token,))
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if not row or not row['arquivo_base64']:
            return 'Documento não encontrado', 404
        
        pdf_data = base64.b64decode(row['arquivo_base64'])
        
        from flask import Response
        return Response(
            pdf_data,
            mimetype='application/pdf',
            headers={'Content-Disposition': f'inline; filename="{row["arquivo_nome"]}"'}
        )
        
    except Exception as e:
        return f'Erro: {str(e)}', 500

@app.route('/api/assinar', methods=['POST'])
def assinar():
    """Processa a assinatura"""
    try:
        data = request.json
        token = data.get('token')
        assinatura_base64 = data.get('assinatura')
        
        if not token or not assinatura_base64:
            return jsonify({'erro': 'Dados incompletos'})
        
        conn = get_db()
        cur = conn.cursor()
        
        # Verificar se já foi assinado
        cur.execute('SELECT assinado FROM signatarios WHERE token = %s', (token,))
        row = cur.fetchone()
        
        if not row:
            cur.close()
            conn.close()
            return jsonify({'erro': 'Token inválido'})
        
        if row['assinado']:
            cur.close()
            conn.close()
            return jsonify({'erro': 'Documento já foi assinado'})
        
        # Registrar assinatura
        cur.execute('''
            UPDATE signatarios 
            SET assinado = TRUE, 
                assinatura_base64 = %s,
                ip_assinatura = %s,
                data_assinatura = %s,
                user_agent = %s
            WHERE token = %s
        ''', (
            assinatura_base64,
            request.remote_addr,
            datetime.now(),
            request.headers.get('User-Agent', ''),
            token
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'sucesso': True})
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/criar_documento', methods=['POST'])
def criar_documento():
    """Cria um novo documento para assinatura (chamado pelo ERP)"""
    try:
        data = request.json
        
        titulo = data.get('titulo', '')
        arquivo_nome = data.get('arquivo_nome', '')
        arquivo_base64 = data.get('arquivo_base64', '')
        signatarios = data.get('signatarios', [])
        criado_por = data.get('criado_por', 'sistema')
        
        if not arquivo_base64 or not signatarios:
            return jsonify({'erro': 'Dados incompletos'})
        
        # Gerar ID do documento
        doc_id = hashlib.sha256(f"{datetime.now().isoformat()}{arquivo_nome}".encode()).hexdigest()[:16]
        
        conn = get_db()
        cur = conn.cursor()
        
        # Inserir documento
        cur.execute('''
            INSERT INTO documentos (doc_id, titulo, arquivo_nome, arquivo_base64, criado_por)
            VALUES (%s, %s, %s, %s, %s)
        ''', (doc_id, titulo, arquivo_nome, arquivo_base64, criado_por))
        
        # Inserir signatários e gerar tokens
        links = []
        for sig in signatarios:
            token = hashlib.sha256(f"{doc_id}{sig['nome']}{datetime.now().isoformat()}".encode()).hexdigest()[:32]
            
            cur.execute('''
                INSERT INTO signatarios (doc_id, nome, email, cpf, token)
                VALUES (%s, %s, %s, %s, %s)
            ''', (doc_id, sig.get('nome', ''), sig.get('email', ''), sig.get('cpf', ''), token))
            
            # Montar URL completa
            base_url = request.host_url.rstrip('/')
            link = f"{base_url}/assinar/{token}"
            
            links.append({
                'nome': sig.get('nome', ''),
                'email': sig.get('email', ''),
                'link': link,
                'token': token
            })
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'sucesso': True,
            'doc_id': doc_id,
            'links': links
        })
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/status/<doc_id>')
def status_documento(doc_id):
    """Retorna status de assinaturas de um documento"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT s.nome, s.email, s.assinado, s.data_assinatura, s.assinatura_base64
            FROM signatarios s
            WHERE s.doc_id = %s
        ''', (doc_id,))
        
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        signatarios = []
        for row in rows:
            signatarios.append({
                'nome': row['nome'],
                'email': row['email'],
                'assinado': row['assinado'],
                'data_assinatura': row['data_assinatura'].strftime('%d/%m/%Y %H:%M') if row['data_assinatura'] else None,
                'assinatura_base64': row['assinatura_base64'] if row['assinado'] else None
            })
        
        return jsonify({
            'doc_id': doc_id,
            'signatarios': signatarios,
            'todos_assinaram': all(s['assinado'] for s in signatarios)
        })
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/documentos')
def listar_documentos():
    """Lista todos os documentos"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT d.doc_id, d.titulo, d.arquivo_nome, d.criado_em, d.criado_por,
                   COUNT(s.id) as total_signatarios,
                   SUM(CASE WHEN s.assinado THEN 1 ELSE 0 END) as assinados
            FROM documentos d
            LEFT JOIN signatarios s ON d.doc_id = s.doc_id
            GROUP BY d.doc_id, d.titulo, d.arquivo_nome, d.criado_em, d.criado_por
            ORDER BY d.criado_em DESC
        ''')
        
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        documentos = []
        for row in rows:
            documentos.append({
                'doc_id': row['doc_id'],
                'titulo': row['titulo'],
                'arquivo_nome': row['arquivo_nome'],
                'criado_em': row['criado_em'].strftime('%d/%m/%Y %H:%M') if row['criado_em'] else '',
                'criado_por': row['criado_por'],
                'total_signatarios': row['total_signatarios'] or 0,
                'assinados': row['assinados'] or 0
            })
        
        return jsonify({'documentos': documentos})
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/download/<doc_id>')
def download_documento(doc_id):
    """Baixa o documento com assinaturas embarcadas"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('SELECT arquivo_base64, arquivo_nome FROM documentos WHERE doc_id = %s', (doc_id,))
        row = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if not row:
            return 'Documento não encontrado', 404
        
        pdf_data = base64.b64decode(row['arquivo_base64'])
        
        from flask import Response
        return Response(
            pdf_data,
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="{row["arquivo_nome"]}"'}
        )
        
    except Exception as e:
        return f'Erro: {str(e)}', 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
