"""
Servidor de Assinaturas Digitais - HAMI ERP
Deploy: Render.com
Versão 2.0 - Com Selfie, Geolocalização e Dossiê Probatório
"""

import os
import json
import hashlib
import base64
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, render_template_string, Response
from flask_cors import CORS
import psycopg
from psycopg.rows import dict_row

# Timezone Brasil (UTC-3)
BRT = timezone(timedelta(hours=-3))

def agora_brasil():
    """Retorna datetime atual no fuso horário do Brasil (BRT)"""
    return datetime.now(BRT)

app = Flask(__name__)
CORS(app)

# Configuração do banco de dados PostgreSQL
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
            arquivo_hash VARCHAR(64),
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            criado_por VARCHAR(100)
        )
    ''')
    
    # Tabela de signatários (atualizada com novos campos)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS signatarios (
            id SERIAL PRIMARY KEY,
            doc_id VARCHAR(64) REFERENCES documentos(doc_id),
            nome VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            cpf VARCHAR(14),
            telefone VARCHAR(20),
            token VARCHAR(64) UNIQUE NOT NULL,
            assinado BOOLEAN DEFAULT FALSE,
            assinatura_base64 TEXT,
            selfie_base64 TEXT,
            ip_assinatura VARCHAR(45),
            data_assinatura TIMESTAMP,
            user_agent TEXT,
            latitude DECIMAL(10, 8),
            longitude DECIMAL(11, 8),
            endereco_aproximado TEXT
        )
    ''')
    
    # Adicionar colunas se não existirem (para bancos existentes)
    try:
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS selfie_base64 TEXT')
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS telefone VARCHAR(20)')
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS latitude DECIMAL(10, 8)')
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS longitude DECIMAL(11, 8)')
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS endereco_aproximado TEXT')
        cur.execute('ALTER TABLE documentos ADD COLUMN IF NOT EXISTS arquivo_hash VARCHAR(64)')
        cur.execute('ALTER TABLE documentos ADD COLUMN IF NOT EXISTS pasta_id INTEGER DEFAULT 1')
    except:
        pass
    
    # Tabela de pastas para organizar documentos
    cur.execute('''
        CREATE TABLE IF NOT EXISTS pastas (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(100) NOT NULL,
            pasta_pai_id INTEGER REFERENCES pastas(id) ON DELETE CASCADE,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            criado_por VARCHAR(100)
        )
    ''')
    
    # Criar pasta raiz se não existir
    cur.execute("INSERT INTO pastas (id, nome, pasta_pai_id, criado_por) VALUES (1, 'Raiz', NULL, 'SISTEMA') ON CONFLICT (id) DO NOTHING")
    
    conn.commit()
    cur.close()
    conn.close()

# Inicializar banco ao iniciar
try:
    init_db()
except:
    pass

# ==================== PÁGINA DE ASSINATURA ====================

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
        h1 { text-align: center; margin-bottom: 10px; color: #4fc3f7; }
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
        .etapa {
            background: rgba(255,255,255,0.1);
            border-radius: 10px;
            padding: 20px;
            margin: 20px 0;
        }
        .etapa h3 { margin-bottom: 15px; color: #4fc3f7; }
        .etapa.concluida { border: 2px solid #4caf50; }
        .etapa.concluida h3::before { content: "✅ "; }
        #canvas-assinatura {
            background: #fff;
            border-radius: 10px;
            cursor: crosshair;
            touch-action: none;
            width: 100%;
            height: 200px;
        }
        #video-selfie, #canvas-selfie {
            width: 100%;
            max-width: 400px;
            border-radius: 10px;
            display: block;
            margin: 0 auto;
        }
        #canvas-selfie { display: none; }
        .preview-selfie {
            max-width: 200px;
            border-radius: 10px;
            margin: 10px auto;
            display: block;
        }
        .botoes {
            display: flex;
            gap: 10px;
            margin-top: 15px;
            flex-wrap: wrap;
            justify-content: center;
        }
        .btn {
            padding: 12px 25px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.3s;
            min-width: 150px;
        }
        .btn-secundario { background: #666; color: #fff; }
        .btn-secundario:hover { background: #555; }
        .btn-primario {
            background: linear-gradient(135deg, #4fc3f7 0%, #2196f3 100%);
            color: #fff;
        }
        .btn-primario:hover { transform: translateY(-2px); box-shadow: 0 5px 20px rgba(79, 195, 247, 0.4); }
        .btn-primario:disabled { background: #666; cursor: not-allowed; transform: none; }
        .btn-sucesso { background: linear-gradient(135deg, #4caf50 0%, #388e3c 100%); color: #fff; }
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
        .localizacao-info {
            font-size: 12px;
            color: #aaa;
            text-align: center;
            margin-top: 10px;
        }
        /* Loading overlay */
        .loading-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            z-index: 9999;
            transition: opacity 0.5s ease-out;
        }
        .loading-overlay.hide {
            opacity: 0;
            pointer-events: none;
        }
        .spinner {
            width: 60px;
            height: 60px;
            border: 4px solid rgba(79, 195, 247, 0.2);
            border-top: 4px solid #4fc3f7;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-bottom: 20px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .loading-text {
            color: #4fc3f7;
            font-size: 18px;
            font-weight: 500;
            margin-bottom: 10px;
        }
        .loading-subtext {
            color: #888;
            font-size: 14px;
            text-align: center;
            max-width: 300px;
        }
        .pulse-dot {
            display: inline-block;
            animation: pulse 1.5s ease-in-out infinite;
        }
        .pulse-dot:nth-child(2) { animation-delay: 0.2s; }
        .pulse-dot:nth-child(3) { animation-delay: 0.4s; }
        @keyframes pulse {
            0%, 60%, 100% { opacity: 0.3; }
            30% { opacity: 1; }
        }
        @media (max-width: 600px) {
            .container { padding: 15px; }
            .botoes { flex-direction: column; }
            .btn { width: 100%; }
        }
    </style>
</head>
<body>
    <!-- Loading Overlay -->
    <div class="loading-overlay" id="loadingOverlay">
        <div class="spinner"></div>
        <div class="loading-text">Carregando documento<span class="pulse-dot">.</span><span class="pulse-dot">.</span><span class="pulse-dot">.</span></div>
        <div class="loading-subtext">Por favor, aguarde enquanto preparamos seu documento para assinatura.</div>
    </div>

    <div class="container">
        <h1>📝 Assinatura Digital</h1>
        <p style="text-align: center; color: #aaa;">HAMI ERP - Sistema de Assinaturas</p>
        
        <div id="conteudo">
            <p style="text-align: center; padding: 50px;">Inicializando...</p>
        </div>
    </div>

    <script>
        const token = '{{ token }}';
        let canvas, ctx;
        let desenhando = false;
        let temAssinatura = false;
        let selfieBase64 = null;
        let localizacao = null;
        let videoStream = null;

        function hideLoading() {
            const overlay = document.getElementById('loadingOverlay');
            if (overlay) {
                overlay.classList.add('hide');
                setTimeout(() => overlay.style.display = 'none', 500);
            }
        }

        async function carregarDocumento() {
            try {
                const resp = await fetch(`/api/documento/${token}`);
                const data = await resp.json();
                
                hideLoading(); // Esconde loading após carregar dados
                
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
                        <div class="sucesso">
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
                    
                    <!-- ETAPA 1: Selfie -->
                    <div class="etapa" id="etapa-selfie">
                        <h3>📸 Etapa 1: Tire uma selfie para validação</h3>
                        <video id="video-selfie" autoplay playsinline></video>
                        <canvas id="canvas-selfie"></canvas>
                        <img id="preview-selfie" class="preview-selfie" style="display: none;">
                        <div class="botoes">
                            <button class="btn btn-primario" id="btn-capturar" onclick="capturarSelfie()">
                                📸 Tirar Foto
                            </button>
                            <button class="btn btn-secundario" id="btn-refazer" onclick="refazerSelfie()" style="display: none;">
                                🔄 Tirar Outra
                            </button>
                        </div>
                    </div>
                    
                    <!-- ETAPA 2: Assinatura -->
                    <div class="etapa" id="etapa-assinatura" style="opacity: 0.5; pointer-events: none;">
                        <h3>✍️ Etapa 2: Desenhe sua assinatura</h3>
                        <canvas id="canvas-assinatura"></canvas>
                        <div class="botoes">
                            <button class="btn btn-secundario" onclick="limparAssinatura()">🗑️ Limpar</button>
                        </div>
                    </div>
                    
                    <!-- ETAPA 3: Confirmar -->
                    <div class="etapa" id="etapa-confirmar" style="opacity: 0.5; pointer-events: none;">
                        <h3>✅ Etapa 3: Confirme sua assinatura</h3>
                        <p class="localizacao-info" id="info-localizacao">📍 Obtendo localização...</p>
                        <div class="botoes">
                            <button class="btn btn-sucesso" id="btn-assinar" onclick="enviarAssinatura()" disabled>
                                ✅ Assinar Documento
                            </button>
                        </div>
                    </div>
                `;
                
                inicializarCamera();
                inicializarCanvas();
                obterLocalizacao();
                
            } catch (e) {
                hideLoading(); // Esconde loading mesmo em caso de erro
                document.getElementById('conteudo').innerHTML = `
                    <div class="erro">
                        <h2>❌ Erro de Conexão</h2>
                        <p>Não foi possível carregar o documento. Tente novamente.</p>
                    </div>
                `;
            }
        }

        async function inicializarCamera() {
            try {
                const video = document.getElementById('video-selfie');
                videoStream = await navigator.mediaDevices.getUserMedia({ 
                    video: { facingMode: 'user', width: 640, height: 480 } 
                });
                video.srcObject = videoStream;
            } catch (e) {
                console.error('Erro ao acessar câmera:', e);
                document.getElementById('etapa-selfie').innerHTML = `
                    <h3>📸 Etapa 1: Selfie</h3>
                    <p style="color: #ff9800; text-align: center; padding: 20px;">
                        ⚠️ Não foi possível acessar a câmera.<br>
                        Verifique as permissões do navegador.
                    </p>
                    <div class="botoes">
                        <button class="btn btn-primario" onclick="pularSelfie()">Continuar sem selfie</button>
                    </div>
                `;
            }
        }

        function pularSelfie() {
            selfieBase64 = null;
            document.getElementById('etapa-selfie').classList.add('concluida');
            document.getElementById('etapa-assinatura').style.opacity = '1';
            document.getElementById('etapa-assinatura').style.pointerEvents = 'auto';
        }

        function capturarSelfie() {
            const video = document.getElementById('video-selfie');
            const canvas = document.getElementById('canvas-selfie');
            const preview = document.getElementById('preview-selfie');
            
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0);
            
            selfieBase64 = canvas.toDataURL('image/jpeg', 0.8);
            
            // Parar câmera e mostrar preview
            if (videoStream) {
                videoStream.getTracks().forEach(track => track.stop());
            }
            video.style.display = 'none';
            preview.src = selfieBase64;
            preview.style.display = 'block';
            
            document.getElementById('btn-capturar').style.display = 'none';
            document.getElementById('btn-refazer').style.display = 'inline-block';
            
            // Liberar próxima etapa
            document.getElementById('etapa-selfie').classList.add('concluida');
            document.getElementById('etapa-assinatura').style.opacity = '1';
            document.getElementById('etapa-assinatura').style.pointerEvents = 'auto';
        }

        function refazerSelfie() {
            selfieBase64 = null;
            document.getElementById('etapa-selfie').classList.remove('concluida');
            document.getElementById('btn-capturar').style.display = 'inline-block';
            document.getElementById('btn-refazer').style.display = 'none';
            document.getElementById('preview-selfie').style.display = 'none';
            document.getElementById('video-selfie').style.display = 'block';
            inicializarCamera();
        }

        function inicializarCanvas() {
            canvas = document.getElementById('canvas-assinatura');
            if (!canvas) return;
            
            ctx = canvas.getContext('2d');
            const rect = canvas.getBoundingClientRect();
            canvas.width = rect.width;
            canvas.height = 200;
            
            ctx.strokeStyle = '#000';
            ctx.lineWidth = 2;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            
            canvas.addEventListener('mousedown', iniciarDesenho);
            canvas.addEventListener('mousemove', desenhar);
            canvas.addEventListener('mouseup', pararDesenho);
            canvas.addEventListener('mouseout', pararDesenho);
            canvas.addEventListener('touchstart', iniciarDesenhoTouch);
            canvas.addEventListener('touchmove', desenharTouch);
            canvas.addEventListener('touchend', pararDesenho);
        }

        function getPos(e) {
            const rect = canvas.getBoundingClientRect();
            return { x: e.clientX - rect.left, y: e.clientY - rect.top };
        }

        function getTouchPos(e) {
            const rect = canvas.getBoundingClientRect();
            const touch = e.touches[0];
            return { x: touch.clientX - rect.left, y: touch.clientY - rect.top };
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
            verificarAssinatura();
        }

        function desenharTouch(e) {
            if (!desenhando) return;
            e.preventDefault();
            const pos = getTouchPos(e);
            ctx.lineTo(pos.x, pos.y);
            ctx.stroke();
            verificarAssinatura();
        }

        function pararDesenho() {
            desenhando = false;
        }

        function verificarAssinatura() {
            temAssinatura = true;
            document.getElementById('etapa-assinatura').classList.add('concluida');
            document.getElementById('etapa-confirmar').style.opacity = '1';
            document.getElementById('etapa-confirmar').style.pointerEvents = 'auto';
            document.getElementById('btn-assinar').disabled = false;
        }

        function limparAssinatura() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            temAssinatura = false;
            document.getElementById('etapa-assinatura').classList.remove('concluida');
            document.getElementById('btn-assinar').disabled = true;
        }

        function obterLocalizacao() {
            if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(
                    (pos) => {
                        localizacao = {
                            latitude: pos.coords.latitude,
                            longitude: pos.coords.longitude
                        };
                        document.getElementById('info-localizacao').innerHTML = 
                            `📍 Localização: ${localizacao.latitude.toFixed(6)}, ${localizacao.longitude.toFixed(6)}`;
                    },
                    (err) => {
                        document.getElementById('info-localizacao').innerHTML = 
                            '📍 Localização não disponível';
                    },
                    { enableHighAccuracy: true, timeout: 10000 }
                );
            }
        }

        async function enviarAssinatura() {
            if (!temAssinatura) {
                alert('Por favor, desenhe sua assinatura.');
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
                        assinatura: assinaturaBase64,
                        selfie: selfieBase64,
                        latitude: localizacao?.latitude,
                        longitude: localizacao?.longitude
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
    """Health check"""
    return jsonify({'status': 'ok', 'timestamp': agora_brasil().isoformat()})

@app.route('/assinar/<token>')
def pagina_assinatura(token):
    """Página de assinatura"""
    return render_template_string(PAGINA_ASSINATURA, token=token)

@app.route('/api/documento/<token>')
def get_documento(token):
    """Retorna informações do documento"""
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
        
        return Response(
            pdf_data,
            mimetype='application/pdf',
            headers={'Content-Disposition': f'inline; filename="{row["arquivo_nome"]}"'}
        )
        
    except Exception as e:
        return f'Erro: {str(e)}', 500

@app.route('/api/assinar', methods=['POST'])
def assinar():
    """Processa a assinatura com selfie e localização"""
    try:
        data = request.json
        token = data.get('token')
        assinatura_base64 = data.get('assinatura')
        selfie_base64 = data.get('selfie')
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        
        if not token or not assinatura_base64:
            return jsonify({'erro': 'Dados incompletos'})
        
        conn = get_db()
        cur = conn.cursor()
        
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
        
        # Registrar assinatura com todos os dados
        cur.execute('''
            UPDATE signatarios 
            SET assinado = TRUE, 
                assinatura_base64 = %s,
                selfie_base64 = %s,
                ip_assinatura = %s,
                data_assinatura = %s,
                user_agent = %s,
                latitude = %s,
                longitude = %s
            WHERE token = %s
        ''', (
            assinatura_base64,
            selfie_base64,
            request.remote_addr,
            agora_brasil(),
            request.headers.get('User-Agent', ''),
            latitude,
            longitude,
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
    """Cria um novo documento para assinatura"""
    try:
        data = request.json
        
        titulo = data.get('titulo', '')
        arquivo_nome = data.get('arquivo_nome', '')
        arquivo_base64 = data.get('arquivo_base64', '')
        signatarios = data.get('signatarios', [])
        criado_por = data.get('criado_por', 'sistema')
        pasta_id = data.get('pasta_id', 1)  # Default para pasta raiz
        
        if not arquivo_base64 or not signatarios:
            return jsonify({'erro': 'Dados incompletos'})
        
        # Gerar hash do documento
        arquivo_bytes = base64.b64decode(arquivo_base64)
        arquivo_hash = hashlib.sha256(arquivo_bytes).hexdigest()
        
        # Gerar ID do documento
        doc_id = hashlib.sha256(f"{datetime.now().isoformat()}{arquivo_nome}".encode()).hexdigest()[:16]
        
        conn = get_db()
        cur = conn.cursor()
        
        # Inserir documento com hash e pasta_id
        cur.execute('''
            INSERT INTO documentos (doc_id, titulo, arquivo_nome, arquivo_base64, arquivo_hash, criado_por, pasta_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (doc_id, titulo, arquivo_nome, arquivo_base64, arquivo_hash, criado_por, pasta_id))
        
        # Inserir signatários
        links = []
        for sig in signatarios:
            token = hashlib.sha256(f"{doc_id}{sig['nome']}{datetime.now().isoformat()}".encode()).hexdigest()[:32]
            
            cur.execute('''
                INSERT INTO signatarios (doc_id, nome, email, cpf, telefone, token)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (doc_id, sig.get('nome', ''), sig.get('email', ''), sig.get('cpf', ''), sig.get('telefone', ''), token))
            
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
            'hash': arquivo_hash,
            'links': links
        })
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/dossie/<doc_id>')
def get_dossie(doc_id):
    """Retorna dossiê probatório completo do documento"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Buscar documento
        cur.execute('''
            SELECT doc_id, titulo, arquivo_nome, arquivo_hash, criado_em, criado_por
            FROM documentos WHERE doc_id = %s
        ''', (doc_id,))
        doc = cur.fetchone()
        
        if not doc:
            return jsonify({'erro': 'Documento não encontrado'})
        
        # Buscar signatários
        cur.execute('''
            SELECT nome, email, cpf, telefone, assinado, assinatura_base64, selfie_base64,
                   ip_assinatura, data_assinatura, user_agent, latitude, longitude, token
            FROM signatarios WHERE doc_id = %s
        ''', (doc_id,))
        signatarios = cur.fetchall()
        
        cur.close()
        conn.close()
        
        # Montar dossiê
        dossie = {
            'documento': {
                'numero': doc['doc_id'],
                'titulo': doc['titulo'],
                'arquivo': doc['arquivo_nome'],
                'hash_sha256': doc['arquivo_hash'],
                'criado_em': doc['criado_em'].strftime('%d/%m/%Y %H:%M:%S') if doc['criado_em'] else '',
                'criado_por': doc['criado_por']
            },
            'signatarios': []
        }
        
        for sig in signatarios:
            sig_info = {
                'nome': sig['nome'],
                'email': sig['email'],
                'cpf': sig['cpf'],
                'telefone': sig['telefone'],
                'token': sig['token'],
                'status': 'ASSINADO' if sig['assinado'] else 'PENDENTE'
            }
            
            if sig['assinado']:
                sig_info['assinatura'] = {
                    'data_hora': sig['data_assinatura'].strftime('%d/%m/%Y %H:%M:%S') if sig['data_assinatura'] else '',
                    'ip': sig['ip_assinatura'],
                    'dispositivo': sig['user_agent'],
                    'localizacao': f"{sig['latitude']}, {sig['longitude']}" if sig['latitude'] else 'Não disponível',
                    'selfie': 'Capturada' if sig['selfie_base64'] else 'Não capturada',
                    'assinatura_imagem': sig['assinatura_base64'][:50] + '...' if sig['assinatura_base64'] else None,
                    'selfie_imagem': sig['selfie_base64'][:50] + '...' if sig['selfie_base64'] else None
                }
            
            dossie['signatarios'].append(sig_info)
        
        todos_assinaram = all(s['status'] == 'ASSINADO' for s in dossie['signatarios'])
        dossie['status'] = 'CONCLUÍDO' if todos_assinaram else 'PENDENTE'
        
        return jsonify(dossie)
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/status/<doc_id>')
def status_documento(doc_id):
    """Retorna status de assinaturas"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT s.nome, s.email, s.assinado, s.data_assinatura
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
                'data_assinatura': row['data_assinatura'].strftime('%d/%m/%Y %H:%M') if row['data_assinatura'] else None
            })
        
        return jsonify({
            'doc_id': doc_id,
            'signatarios': signatarios,
            'todos_assinaram': all(s['assinado'] for s in signatarios)
        })
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/pdf_assinado/<doc_id>')
def get_pdf_assinado(doc_id):
    """Gera e retorna PDF com assinaturas aplicadas"""
    try:
        from io import BytesIO
        from PyPDF2 import PdfReader, PdfWriter
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        from PIL import Image
        
        conn = get_db()
        cur = conn.cursor()
        
        # Buscar documento
        cur.execute('''
            SELECT doc_id, titulo, arquivo_nome, arquivo_base64, arquivo_hash, criado_em
            FROM documentos WHERE doc_id = %s
        ''', (doc_id,))
        doc = cur.fetchone()
        
        if not doc or not doc['arquivo_base64']:
            cur.close()
            conn.close()
            return jsonify({'erro': 'Documento não encontrado'}), 404
        
        # Buscar signatários que assinaram
        cur.execute('''
            SELECT nome, email, cpf, assinado, assinatura_base64, selfie_base64,
                   data_assinatura, ip_assinatura, latitude, longitude
            FROM signatarios WHERE doc_id = %s
        ''', (doc_id,))
        signatarios = cur.fetchall()
        
        cur.close()
        conn.close()
        
        # Verificar se todos assinaram
        todos_assinaram = all(s['assinado'] for s in signatarios)
        if not todos_assinaram:
            return jsonify({'erro': 'Documento ainda não foi totalmente assinado'}), 400
        
        # Decodificar PDF original
        pdf_original = base64.b64decode(doc['arquivo_base64'])
        
        # Ler PDF original
        reader = PdfReader(BytesIO(pdf_original))
        writer = PdfWriter()
        
        # Copiar todas as páginas do original
        for page in reader.pages:
            writer.add_page(page)
        
        # Criar página de assinaturas
        sig_buffer = BytesIO()
        c = canvas.Canvas(sig_buffer, pagesize=A4)
        width, height = A4
        
        # Cabeçalho
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height - 50, "FOLHA DE ASSINATURAS DIGITAIS")
        
        c.setFont("Helvetica", 10)
        c.drawString(50, height - 70, f"Documento: {doc['titulo'] or doc['arquivo_nome']}")
        c.drawString(50, height - 85, f"Hash SHA-256: {doc['arquivo_hash'][:32]}...")
        c.drawString(50, height - 100, f"Criado em: {doc['criado_em'].strftime('%d/%m/%Y %H:%M:%S') if doc['criado_em'] else ''}")
        
        c.line(50, height - 115, width - 50, height - 115)
        
        # Posição inicial para assinaturas
        y_pos = height - 150
        
        for sig in signatarios:
            if sig['assinado']:
                # Nome do signatário
                c.setFont("Helvetica-Bold", 11)
                c.drawString(50, y_pos, f"Signatário: {sig['nome']}")
                y_pos -= 15
                
                c.setFont("Helvetica", 9)
                if sig['email']:
                    c.drawString(50, y_pos, f"Email: {sig['email']}")
                    y_pos -= 12
                if sig['cpf']:
                    c.drawString(50, y_pos, f"CPF: {sig['cpf']}")
                    y_pos -= 12
                if sig['data_assinatura']:
                    c.drawString(50, y_pos, f"Data: {sig['data_assinatura'].strftime('%d/%m/%Y %H:%M:%S')}")
                    y_pos -= 12
                if sig['ip_assinatura']:
                    c.drawString(50, y_pos, f"IP: {sig['ip_assinatura']}")
                    y_pos -= 12
                if sig['latitude'] and sig['longitude']:
                    c.drawString(50, y_pos, f"Localização: {sig['latitude']}, {sig['longitude']}")
                    y_pos -= 12
                
                y_pos -= 5
                
                # Desenhar imagem de assinatura
                if sig['assinatura_base64']:
                    try:
                        # Remover prefixo data:image/png;base64, se existir
                        img_data = sig['assinatura_base64']
                        if ',' in img_data:
                            img_data = img_data.split(',')[1]
                        
                        img_bytes = base64.b64decode(img_data)
                        img = Image.open(BytesIO(img_bytes))
                        
                        # Redimensionar mantendo proporção
                        max_width = 150
                        max_height = 60
                        img.thumbnail((max_width, max_height), Image.LANCZOS)
                        
                        # Desenhar no canvas
                        img_buffer = BytesIO()
                        img.save(img_buffer, format='PNG')
                        img_buffer.seek(0)
                        
                        c.drawImage(ImageReader(img_buffer), 50, y_pos - img.height, 
                                   width=img.width, height=img.height)
                        y_pos -= img.height + 10
                    except Exception as e:
                        c.drawString(50, y_pos, f"[Erro ao carregar assinatura: {str(e)[:50]}]")
                        y_pos -= 15
                
                # Desenhar selfie (menor)
                if sig['selfie_base64']:
                    try:
                        img_data = sig['selfie_base64']
                        if ',' in img_data:
                            img_data = img_data.split(',')[1]
                        
                        img_bytes = base64.b64decode(img_data)
                        img = Image.open(BytesIO(img_bytes))
                        
                        max_width = 60
                        max_height = 60
                        img.thumbnail((max_width, max_height), Image.LANCZOS)
                        
                        img_buffer = BytesIO()
                        img.save(img_buffer, format='JPEG')
                        img_buffer.seek(0)
                        
                        c.drawImage(ImageReader(img_buffer), 220, y_pos, 
                                   width=img.width, height=img.height)
                    except:
                        pass
                
                y_pos -= 20
                c.line(50, y_pos, width - 50, y_pos)
                y_pos -= 20
                
                # Nova página se necessário
                if y_pos < 100:
                    c.showPage()
                    y_pos = height - 50
        
        # Rodapé
        c.setFont("Helvetica", 8)
        c.drawString(50, 30, "Documento assinado digitalmente via HAMI ERP - Sistema de Assinaturas Digitais")
        c.drawString(50, 18, f"Gerado em: {agora_brasil().strftime('%d/%m/%Y %H:%M:%S')} (Horário de Brasília)")
        
        c.save()
        
        # Adicionar página de assinaturas ao PDF
        sig_buffer.seek(0)
        sig_reader = PdfReader(sig_buffer)
        for page in sig_reader.pages:
            writer.add_page(page)
        
        # Gerar PDF final
        output = BytesIO()
        writer.write(output)
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="ASSINADO_{doc["arquivo_nome"]}"',
                'Content-Type': 'application/pdf'
            }
        )
        
    except ImportError as e:
        return jsonify({'erro': f'Dependências não instaladas: {e}'}), 500
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/documento/<token>/download')
def download_documento(token):
    """Baixa o PDF do documento assinado"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Buscar documento pelo token do signatário
        cur.execute('''
            SELECT d.arquivo_base64, d.arquivo_nome, d.doc_id
            FROM signatarios s
            JOIN documentos d ON s.doc_id = d.doc_id
            WHERE s.token = %s
        ''', (token,))
        
        row = cur.fetchone()
        
        # Se não encontrou pelo token do signatário, tentar pelo doc_id
        if not row:
            cur.execute('''
                SELECT arquivo_base64, arquivo_nome, doc_id
                FROM documentos WHERE doc_id = %s
            ''', (token,))
            row = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if not row or not row['arquivo_base64']:
            return jsonify({'erro': 'Documento não encontrado'}), 404
        
        pdf_data = base64.b64decode(row['arquivo_base64'])
        
        return Response(
            pdf_data,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="ASSINADO_{row["arquivo_nome"]}"',
                'Content-Type': 'application/pdf'
            }
        )
        
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

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

# ==================== API DE PASTAS ====================

@app.route('/api/pastas')
def listar_pastas():
    """Lista todas as pastas"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT id, nome, pasta_pai_id, criado_em, criado_por
            FROM pastas
            ORDER BY pasta_pai_id NULLS FIRST, nome
        ''')
        
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        pastas = []
        for row in rows:
            pastas.append({
                'id': row['id'],
                'nome': row['nome'],
                'pasta_pai_id': row['pasta_pai_id'],
                'criado_em': row['criado_em'].strftime('%d/%m/%Y %H:%M') if row['criado_em'] else '',
                'criado_por': row['criado_por']
            })
        
        return jsonify({'pastas': pastas})
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/pastas', methods=['POST'])
def criar_pasta():
    """Cria uma nova pasta"""
    try:
        data = request.json
        nome = data.get('nome', '').strip()
        pasta_pai_id = data.get('pasta_pai_id', 1)
        criado_por = data.get('criado_por', 'sistema')
        
        if not nome:
            return jsonify({'erro': 'Nome da pasta é obrigatório'})
        
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            INSERT INTO pastas (nome, pasta_pai_id, criado_por)
            VALUES (%s, %s, %s)
            RETURNING id
        ''', (nome, pasta_pai_id if pasta_pai_id else None, criado_por))
        
        pasta_id = cur.fetchone()['id']
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'sucesso': True, 'pasta_id': pasta_id})
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/pastas/<int:pasta_id>', methods=['PUT'])
def renomear_pasta(pasta_id):
    """Renomeia uma pasta"""
    try:
        if pasta_id == 1:
            return jsonify({'erro': 'Não é possível renomear a pasta raiz'})
        
        data = request.json
        novo_nome = data.get('nome', '').strip()
        
        if not novo_nome:
            return jsonify({'erro': 'Nome da pasta é obrigatório'})
        
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('UPDATE pastas SET nome = %s WHERE id = %s', (novo_nome, pasta_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'sucesso': True})
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/pastas/<int:pasta_id>', methods=['DELETE'])
def excluir_pasta(pasta_id):
    """Exclui uma pasta (apenas se estiver vazia)"""
    try:
        if pasta_id == 1:
            return jsonify({'erro': 'Não é possível excluir a pasta raiz'})
        
        conn = get_db()
        cur = conn.cursor()
        
        # Verificar se há documentos na pasta
        cur.execute('SELECT COUNT(*) as count FROM documentos WHERE pasta_id = %s', (pasta_id,))
        if cur.fetchone()['count'] > 0:
            cur.close()
            conn.close()
            return jsonify({'erro': 'Pasta contém documentos. Mova-os antes de excluir.'})
        
        # Verificar se há subpastas
        cur.execute('SELECT COUNT(*) as count FROM pastas WHERE pasta_pai_id = %s', (pasta_id,))
        if cur.fetchone()['count'] > 0:
            cur.close()
            conn.close()
            return jsonify({'erro': 'Pasta contém subpastas. Exclua-as primeiro.'})
        
        cur.execute('DELETE FROM pastas WHERE id = %s', (pasta_id,))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'sucesso': True})
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/documentos/<doc_id>/mover', methods=['POST'])
def mover_documento(doc_id):
    """Move um documento para outra pasta"""
    try:
        data = request.json
        pasta_destino_id = data.get('pasta_id', 1)
        
        conn = get_db()
        cur = conn.cursor()
        
        # Verificar se a pasta destino existe
        cur.execute('SELECT id FROM pastas WHERE id = %s', (pasta_destino_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'erro': 'Pasta destino não encontrada'})
        
        cur.execute('UPDATE documentos SET pasta_id = %s WHERE doc_id = %s', (pasta_destino_id, doc_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'sucesso': True})
        
    except Exception as e:
        return jsonify({'erro': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
