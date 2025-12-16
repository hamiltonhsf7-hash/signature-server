"""
Servidor de Assinaturas Digitais - HAMI ERP
Deploy: Render.com
Versão 2.0 - Com Selfie, Geolocalização e Dossiê Probatório
"""

import os
import json
import hashlib
import base64
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, render_template_string, Response, redirect
from flask_cors import CORS
import psycopg
from psycopg.rows import dict_row
import qrcode
import threading

# Timezone Brasil (UTC-3)
BRT = timezone(timedelta(hours=-3))

def agora_brasil():
    """Retorna datetime atual no fuso horário do Brasil (BRT)"""
    return datetime.now(BRT)

app = Flask(__name__)
CORS(app)

# Configuração do banco de dados PostgreSQL
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Configuração Resend para envio de emails
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'onboarding@resend.dev')
EMAIL_ENABLED = os.environ.get('EMAIL_ENABLED', 'true').lower() == 'true'
# Para testes: se configurado, todos os emails vão para este endereço
EMAIL_TEST_OVERRIDE = os.environ.get('EMAIL_TEST_OVERRIDE', '')

def get_db():
    """Retorna conexão com o banco de dados"""
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return conn

def enviar_email_assinatura(email_destino, assunto, corpo_html, anexo_pdf=None, nome_anexo=None):
    """Envia email usando API do Resend (HTTP)"""
    print(f"[EMAIL] Iniciando envio via Resend para: {email_destino}")
    print(f"[EMAIL] RESEND_API_KEY configurada: {bool(RESEND_API_KEY)}, EMAIL_ENABLED: {EMAIL_ENABLED}")
    
    if not EMAIL_ENABLED or not RESEND_API_KEY:
        print(f"[EMAIL] Email desabilitado ou API Key não configurada. Destino: {email_destino}")
        return False
    
    try:
        # Se EMAIL_TEST_OVERRIDE configurado, redireciona todos emails para teste
        email_final = EMAIL_TEST_OVERRIDE if EMAIL_TEST_OVERRIDE else email_destino
        if EMAIL_TEST_OVERRIDE:
            print(f"[EMAIL] ⚠️ Modo teste: redirecionando de {email_destino} para {EMAIL_TEST_OVERRIDE}")
        
        print(f"[EMAIL] Montando payload...")
        
        # Payload para API do Resend
        payload = {
            "from": EMAIL_FROM,
            "to": [email_final],
            "subject": assunto,
            "html": corpo_html
        }
        
        # Converter para JSON
        data = json.dumps(payload).encode('utf-8')
        
        # Criar request
        print(f"[EMAIL] Enviando para API Resend...")
        req = urllib.request.Request(
            'https://api.resend.com/emails',
            data=data,
            headers={
                'Authorization': f'Bearer {RESEND_API_KEY}',
                'Content-Type': 'application/json'
            },
            method='POST'
        )
        
        # Enviar request
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            print(f"[EMAIL] ✅ Email enviado com sucesso! ID: {result.get('id', 'N/A')}")
            return True
        
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else 'No body'
        print(f"[EMAIL] ❌ Erro HTTP {e.code}: {error_body}")
        return False
    except Exception as e:
        import traceback
        print(f"[EMAIL] ❌ Erro ao enviar email: {e}")
        traceback.print_exc()
        return False

def notificar_assinatura_individual(doc_id, signatario_nome, todos_assinaram=False):
    """Notifica o criador do documento sobre uma assinatura individual"""
    try:
        print(f"[EMAIL] Iniciando notificação para doc_id: {doc_id}, signatario: {signatario_nome}")
        
        conn = get_db()
        cur = conn.cursor()
        
        # Buscar documento e email do criador
        cur.execute('''
            SELECT titulo, arquivo_nome, criado_por, email_criador
            FROM documentos WHERE doc_id = %s
        ''', (doc_id,))
        doc = cur.fetchone()
        
        print(f"[EMAIL] Documento encontrado: {doc}")
        
        if not doc or not doc.get('email_criador'):
            print(f"[EMAIL] Email criador não encontrado ou vazio para doc_id: {doc_id}")
            cur.close()
            conn.close()
            return False
        
        # Buscar total e status dos signatários
        cur.execute('''
            SELECT COUNT(*) as total, 
                   SUM(CASE WHEN assinado THEN 1 ELSE 0 END) as assinados
            FROM signatarios WHERE doc_id = %s
        ''', (doc_id,))
        stats = cur.fetchone()
        
        cur.close()
        conn.close()
        
        total = stats['total']
        assinados = stats['assinados']
        
        # Montar email
        if todos_assinaram:
            assunto = f"✅ Documento CONCLUÍDO: {doc['titulo'] or doc['arquivo_nome']}"
            corpo = f"""
            <html>
            <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                    <h1 style="color: #4caf50; text-align: center;">✅ Documento Concluído!</h1>
                    <p style="font-size: 16px; color: #333;">Olá <strong>{doc['criado_por']}</strong>,</p>
                    <p style="font-size: 16px; color: #333;">Ótima notícia! <strong>Todos os signatários</strong> assinaram o documento:</p>
                    <div style="background: #e8f5e9; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #4caf50;">
                        <p style="margin: 0; font-size: 18px; font-weight: bold; color: #2e7d32;">📄 {doc['titulo'] or doc['arquivo_nome']}</p>
                        <p style="margin: 10px 0 0; color: #388e3c;">Status: {assinados}/{total} assinaturas ✅</p>
                    </div>
                    <p style="font-size: 14px; color: #666;">O documento assinado está disponível no módulo de Assinaturas do HAMI ERP.</p>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                    <p style="font-size: 12px; color: #999; text-align: center;">HAMI ERP - Sistema de Gestão Empresarial</p>
                </div>
            </body>
            </html>
            """
        else:
            assunto = f"📝 Nova Assinatura: {doc['titulo'] or doc['arquivo_nome']}"
            corpo = f"""
            <html>
            <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                    <h1 style="color: #2196f3; text-align: center;">📝 Nova Assinatura Registrada</h1>
                    <p style="font-size: 16px; color: #333;">Olá <strong>{doc['criado_por']}</strong>,</p>
                    <p style="font-size: 16px; color: #333;">O signatário <strong>{signatario_nome}</strong> assinou o documento:</p>
                    <div style="background: #e3f2fd; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #2196f3;">
                        <p style="margin: 0; font-size: 18px; font-weight: bold; color: #1565c0;">📄 {doc['titulo'] or doc['arquivo_nome']}</p>
                        <p style="margin: 10px 0 0; color: #1976d2;">Progresso: {assinados}/{total} assinaturas</p>
                    </div>
                    <p style="font-size: 14px; color: #666;">Acompanhe o status completo no módulo de Assinaturas do HAMI ERP.</p>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                    <p style="font-size: 12px; color: #999; text-align: center;">HAMI ERP - Sistema de Gestão Empresarial</p>
                </div>
            </body>
            </html>
            """
        
        return enviar_email_assinatura(doc['email_criador'], assunto, corpo)
        
    except Exception as e:
        print(f"[EMAIL] Erro ao notificar assinatura: {e}")
        return False

def notificar_assinatura_async(doc_id, signatario_nome, todos_assinaram=False):
    """Wrapper assíncrono para notificar_assinatura_individual - evita timeout do worker"""
    def _enviar():
        try:
            notificar_assinatura_individual(doc_id, signatario_nome, todos_assinaram)
        except Exception as e:
            print(f"[EMAIL] Erro na thread de email: {e}")
    
    thread = threading.Thread(target=_enviar, daemon=True)
    thread.start()
    print(f"[EMAIL] Thread de notificação iniciada para doc_id: {doc_id}")


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
            endereco_aproximado TEXT,
            data_nascimento DATE
        )
    ''')
    
    # Adicionar colunas se não existirem (para bancos existentes)
    try:
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS selfie_base64 TEXT')
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS telefone VARCHAR(20)')
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS latitude DECIMAL(10, 8)')
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS longitude DECIMAL(11, 8)')
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS endereco_aproximado TEXT')
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS data_nascimento DATE')
        cur.execute('ALTER TABLE documentos ADD COLUMN IF NOT EXISTS arquivo_hash VARCHAR(64)')
        cur.execute('ALTER TABLE documentos ADD COLUMN IF NOT EXISTS pasta_id INTEGER DEFAULT 1')
        cur.execute('ALTER TABLE documentos ADD COLUMN IF NOT EXISTS email_criador VARCHAR(255)')
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
    
    # Tabela de log de auditoria com hash encadeado (blockchain-like)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS log_auditoria (
            id SERIAL PRIMARY KEY,
            doc_id VARCHAR(64),
            acao VARCHAR(50) NOT NULL,
            usuario VARCHAR(200),
            ip VARCHAR(50),
            user_agent TEXT,
            dados_adicionais JSONB,
            hash_anterior VARCHAR(64),
            hash_registro VARCHAR(64),
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Criar pasta raiz se não existir
    cur.execute("INSERT INTO pastas (id, nome, pasta_pai_id, criado_por) VALUES (1, 'Raiz', NULL, 'SISTEMA') ON CONFLICT (id) DO NOTHING")
    
    # Adicionar colunas de aceite de termos se não existirem
    try:
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS aceite_termos BOOLEAN DEFAULT FALSE')
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS data_aceite TIMESTAMP')
        cur.execute('ALTER TABLE signatarios ADD COLUMN IF NOT EXISTS hash_aceite VARCHAR(64)')
    except:
        pass
    
    conn.commit()
    cur.close()
    conn.close()

# ==================== FUNÇÕES AUXILIARES ====================

def validar_cpf(cpf):
    """Valida CPF usando algoritmo oficial dos dígitos verificadores"""
    # Remove caracteres não numéricos
    cpf = ''.join(filter(str.isdigit, cpf))
    
    # CPF deve ter 11 dígitos
    if len(cpf) != 11:
        return False, "CPF deve ter 11 dígitos"
    
    # CPFs inválidos conhecidos (todos dígitos iguais)
    cpfs_invalidos = [str(i) * 11 for i in range(10)]
    if cpf in cpfs_invalidos:
        return False, "CPF inválido"
    
    # Calcula primeiro dígito verificador
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    resto = soma % 11
    digito1 = 0 if resto < 2 else 11 - resto
    
    if int(cpf[9]) != digito1:
        return False, "CPF inválido - dígito verificador incorreto"
    
    # Calcula segundo dígito verificador
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    resto = soma % 11
    digito2 = 0 if resto < 2 else 11 - resto
    
    if int(cpf[10]) != digito2:
        return False, "CPF inválido - dígito verificador incorreto"
    
    return True, "CPF válido"

def registrar_auditoria(doc_id, acao, usuario=None, ip=None, user_agent=None, dados_adicionais=None):
    """Registra ação no log de auditoria com hash encadeado"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Buscar hash do último registro para encadeamento
        cur.execute('SELECT hash_registro FROM log_auditoria ORDER BY id DESC LIMIT 1')
        row = cur.fetchone()
        hash_anterior = row['hash_registro'] if row else '0' * 64
        
        # Criar dados para hash
        timestamp = datetime.now(BRT).isoformat()
        dados_hash = f"{doc_id}|{acao}|{usuario}|{ip}|{timestamp}|{hash_anterior}"
        hash_registro = hashlib.sha256(dados_hash.encode()).hexdigest()
        
        # Inserir registro
        cur.execute('''
            INSERT INTO log_auditoria (doc_id, acao, usuario, ip, user_agent, dados_adicionais, hash_anterior, hash_registro)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (doc_id, acao, usuario, ip, user_agent, json.dumps(dados_adicionais) if dados_adicionais else None, hash_anterior, hash_registro))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Erro ao registrar auditoria: {e}")
        return False

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
            height: 150px;  /* Mais retangular horizontalmente */
        }
        /* Modo tela cheia para assinatura */
        .fullscreen-container {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(0,0,0,0.95);
            z-index: 9999;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .fullscreen-container canvas {
            width: 95vw !important;
            height: 60vh !important;
            max-height: 400px;
            background: #fff;
            border-radius: 15px;
        }
        .fullscreen-container .botoes {
            margin-top: 20px;
        }
        .fullscreen-container h3 {
            color: #fff;
            margin-bottom: 15px;
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
        .form-group {
            margin-bottom: 15px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            color: #4fc3f7;
            font-weight: 500;
        }
        .form-group input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid rgba(255,255,255,0.2);
            border-radius: 8px;
            background: rgba(255,255,255,0.1);
            color: #fff;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        .form-group input:focus {
            outline: none;
            border-color: #4fc3f7;
        }
        .form-group input::placeholder {
            color: rgba(255,255,255,0.5);
        }
        .erro-validacao {
            background: rgba(244, 67, 54, 0.2);
            border: 1px solid #f44336;
            color: #ff8a80;
            padding: 15px;
            border-radius: 10px;
            margin-top: 15px;
            display: none;
        }
        .sucesso-validacao {
            background: rgba(76, 175, 80, 0.2);
            border: 1px solid #4caf50;
            color: #a5d6a7;
            padding: 15px;
            border-radius: 10px;
            margin-top: 15px;
            display: none;
        }
        .etapa.bloqueada {
            opacity: 0.3;
            pointer-events: none;
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
                            <div style="margin-top: 25px; display: flex; flex-direction: column; gap: 15px; align-items: center;">
                                <a href="/api/documento/${token}/download" class="btn btn-primario" style="text-decoration: none; display: inline-block; padding: 12px 25px;">
                                    📄 Baixar Documento Original
                                </a>
                                <a href="/api/pdf_assinado_por_token/${token}" class="btn btn-sucesso" style="text-decoration: none; display: inline-block; padding: 12px 25px;">
                                    ✅ Baixar Documento Assinado
                                </a>
                            </div>
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
                    
                    <!-- ETAPA 0: Validação de Identidade -->
                    <div class="etapa" id="etapa-validacao">
                        <h3>🔐 Etapa 1: Confirme sua identidade</h3>
                        <p style="margin-bottom: 15px; color: #aaa;">Para sua segurança, informe seus dados cadastrais.</p>
                        <div class="form-group">
                            <label for="input-cpf">CPF</label>
                            <input type="text" id="input-cpf" placeholder="000.000.000-00" maxlength="14" oninput="formatarCPF(this)">
                        </div>
                        <div class="form-group">
                            <label for="input-nascimento">Data de Nascimento</label>
                            <input type="text" id="input-nascimento" placeholder="DD/MM/AAAA" maxlength="10" oninput="formatarData(this)">
                        </div>
                        <div id="erro-validacao" class="erro-validacao"></div>
                        <div id="sucesso-validacao" class="sucesso-validacao"></div>
                        <div class="botoes">
                            <button class="btn btn-primario" id="btn-validar" onclick="validarDados()">
                                🔍 Validar Dados
                            </button>
                        </div>
                    </div>
                    
                    <!-- ETAPA 1: Selfie (bloqueada até validação) -->
                    <div class="etapa bloqueada" id="etapa-selfie">
                        <h3>📸 Etapa 2: Tire uma selfie para validação</h3>
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
                    <div class="etapa bloqueada" id="etapa-assinatura">
                        <h3>✍️ Etapa 3: Desenhe sua assinatura</h3>
                        <canvas id="canvas-assinatura"></canvas>
                        <div class="botoes">
                            <button class="btn btn-secundario" onclick="limparAssinatura()">🗑️ Limpar</button>
                        </div>
                    </div>
                    
                    <!-- ETAPA 3: Confirmar -->
                    <div class="etapa bloqueada" id="etapa-confirmar">
                        <h3>✅ Etapa 4: Confirme sua assinatura</h3>
                        <p class="localizacao-info" id="info-localizacao">📍 Obtendo localização...</p>
                        
                        <!-- Aviso de termos -->
                        <div class="termos-aceite" style="background: rgba(76, 175, 80, 0.1); padding: 15px; border-radius: 10px; margin: 15px 0; border: 1px solid rgba(76, 175, 80, 0.4);">
                            <p style="color: #a5d6a7; font-size: 14px; line-height: 1.6; margin: 0;">
                                📋 <strong>Ao clicar em "Assinar Documento"</strong>, você declara que leu e compreendeu o documento acima, 
                                concorda com seus termos e reconhece a validade jurídica desta assinatura eletrônica.
                                <a href="#" onclick="abrirTermos(); return false;" style="color: #4fc3f7; text-decoration: underline;">Ver termos completos</a>
                            </p>
                        </div>
                        
                        <div class="botoes">
                            <button class="btn btn-sucesso" id="btn-assinar" onclick="enviarAssinatura()" disabled>
                                ✅ Assinar Documento
                            </button>
                        </div>
                    </div>
                `;
                
                // Não inicializa câmera aqui - espera validação
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

        // Formatar CPF com máscara
        function formatarCPF(input) {
            let value = input.value.replace(/\D/g, '');
            if (value.length > 11) value = value.slice(0, 11);
            
            if (value.length > 9) {
                value = value.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, '$1.$2.$3-$4');
            } else if (value.length > 6) {
                value = value.replace(/^(\d{3})(\d{3})(\d{0,3})$/, '$1.$2.$3');
            } else if (value.length > 3) {
                value = value.replace(/^(\d{3})(\d{0,3})$/, '$1.$2');
            }
            input.value = value;
        }

        // Formatar Data com máscara DD/MM/AAAA
        function formatarData(input) {
            let value = input.value.replace(/\D/g, '');
            if (value.length > 8) value = value.slice(0, 8);
            
            if (value.length > 4) {
                value = value.replace(/^(\d{2})(\d{2})(\d{0,4})$/, '$1/$2/$3');
            } else if (value.length > 2) {
                value = value.replace(/^(\d{2})(\d{0,2})$/, '$1/$2');
            }
            input.value = value;
        }

        // Validar dados do signatário
        async function validarDados() {
            const cpf = document.getElementById('input-cpf').value;
            const nascimento = document.getElementById('input-nascimento').value;
            const erroDiv = document.getElementById('erro-validacao');
            const sucessoDiv = document.getElementById('sucesso-validacao');
            const btnValidar = document.getElementById('btn-validar');
            
            erroDiv.style.display = 'none';
            sucessoDiv.style.display = 'none';
            
            if (!cpf || !nascimento) {
                erroDiv.textContent = 'Por favor, preencha o CPF e a data de nascimento.';
                erroDiv.style.display = 'block';
                return;
            }
            
            btnValidar.disabled = true;
            btnValidar.textContent = '⏳ Validando...';
            
            try {
                const resp = await fetch('/api/validar_signatario', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        token: token,
                        cpf: cpf,
                        data_nascimento: nascimento
                    })
                });
                
                const data = await resp.json();
                
                if (data.valido) {
                    sucessoDiv.textContent = '✅ ' + (data.mensagem || 'Dados validados com sucesso!');
                    sucessoDiv.style.display = 'block';
                    
                    // Marcar etapa como concluída
                    document.getElementById('etapa-validacao').classList.add('concluida');
                    
                    // Desbloquear etapa de selfie
                    document.getElementById('etapa-selfie').classList.remove('bloqueada');
                    
                    // Desabilitar campos para evitar alteração
                    document.getElementById('input-cpf').disabled = true;
                    document.getElementById('input-nascimento').disabled = true;
                    btnValidar.style.display = 'none';
                    
                    // Iniciar câmera para selfie
                    inicializarCamera();
                } else {
                    erroDiv.textContent = '❌ ' + (data.erro || 'Dados não conferem com o cadastro.');
                    erroDiv.style.display = 'block';
                    btnValidar.disabled = false;
                    btnValidar.textContent = '🔍 Validar Dados';
                }
                
            } catch (e) {
                erroDiv.textContent = '❌ Erro ao validar dados. Tente novamente.';
                erroDiv.style.display = 'block';
                btnValidar.disabled = false;
                btnValidar.textContent = '🔍 Validar Dados';
            }
        }

        async function inicializarCamera() {
            try {
                const video = document.getElementById('video-selfie');
                videoStream = await navigator.mediaDevices.getUserMedia({ 
                    video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } }  // HD para melhor qualidade
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
            document.getElementById('etapa-assinatura').classList.remove('bloqueada');
        }

        function capturarSelfie() {
            const video = document.getElementById('video-selfie');
            const canvas = document.getElementById('canvas-selfie');
            const preview = document.getElementById('preview-selfie');
            
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0);
            
            selfieBase64 = canvas.toDataURL('image/jpeg', 0.95);  // Alta qualidade
            
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
            document.getElementById('etapa-assinatura').classList.remove('bloqueada');
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
            const infoEl = document.getElementById('info-localizacao');
            
            // Função para buscar localização por IP (fallback)
            async function buscarPorIP() {
                try {
                    infoEl.innerHTML = '📍 Obtendo localização por IP...';
                    const resp = await fetch('https://ipapi.co/json/');
                    const data = await resp.json();
                    if (data.latitude && data.longitude) {
                        localizacao = {
                            latitude: data.latitude,
                            longitude: data.longitude,
                            cidade: data.city,
                            estado: data.region,
                            pais: data.country_name,
                            fonte: 'IP'
                        };
                        infoEl.innerHTML = `📍 Localização (IP): ${data.city || 'N/A'}, ${data.region || 'N/A'}<br>📌 Coordenadas: ${data.latitude.toFixed(6)}, ${data.longitude.toFixed(6)}`;
                    } else {
                        infoEl.innerHTML = '📍 Localização não disponível';
                    }
                } catch (e) {
                    console.error('Erro ao buscar localização por IP:', e);
                    infoEl.innerHTML = '📍 Localização não disponível';
                }
            }
            
            // Tentar GPS primeiro
            if (navigator.geolocation) {
                infoEl.innerHTML = '📍 Obtendo localização GPS...';
                navigator.geolocation.getCurrentPosition(
                    (pos) => {
                        localizacao = {
                            latitude: pos.coords.latitude,
                            longitude: pos.coords.longitude,
                            precisao: pos.coords.accuracy,
                            fonte: 'GPS'
                        };
                        infoEl.innerHTML = `📍 Localização (GPS): ${localizacao.latitude.toFixed(6)}, ${localizacao.longitude.toFixed(6)}`;
                    },
                    (err) => {
                        console.log('GPS não disponível, tentando IP:', err.message);
                        buscarPorIP();
                    },
                    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
                );
            } else {
                // Navegador não suporta geolocalização, tentar IP
                buscarPorIP();
            }
        }

        // Abrir modal com termos completos
        function abrirTermos() {
            const modal = document.createElement('div');
            modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.9); z-index: 9999; display: flex; align-items: center; justify-content: center; padding: 20px;';
            modal.innerHTML = `
                <div style="background: #1a1a2e; border-radius: 15px; padding: 25px; max-width: 600px; max-height: 80vh; overflow-y: auto; border: 1px solid #4fc3f7;">
                    <h2 style="color: #4fc3f7; margin-bottom: 15px;">📋 Termos de Assinatura Eletrônica</h2>
                    <div style="color: #ccc; font-size: 14px; line-height: 1.7;">
                        <p style="margin-bottom: 12px;"><strong>Ao assinar este documento, você declara que:</strong></p>
                        <ul style="margin-left: 20px; margin-bottom: 15px;">
                            <li>Leu e compreendeu integralmente o conteúdo do documento;</li>
                            <li>Concorda com todos os termos e condições apresentados;</li>
                            <li>Confirma que os dados pessoais informados são verdadeiros;</li>
                            <li>Autoriza a coleta de dados de identificação (selfie, IP, localização) para fins de autenticação;</li>
                        </ul>
                        <p style="margin-bottom: 12px;"><strong>Base Legal:</strong></p>
                        <p style="margin-bottom: 10px;">Esta assinatura eletrônica tem validade jurídica conforme:</p>
                        <ul style="margin-left: 20px; margin-bottom: 15px;">
                            <li><strong>Medida Provisória 2.200-2/2001</strong> - Institui a ICP-Brasil</li>
                            <li><strong>Lei 14.063/2020</strong> - Dispõe sobre assinaturas eletrônicas</li>
                            <li><strong>Art. 219 do Código Civil</strong> - Declarações de vontade</li>
                        </ul>
                        <p style="color: #a5d6a7;">As partes reconhecem que as assinaturas eletrônicas apostas têm a mesma validade e eficácia de assinaturas manuscritas.</p>
                    </div>
                    <button onclick="this.parentElement.parentElement.remove();" style="margin-top: 20px; padding: 12px 30px; background: #4fc3f7; color: #000; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; width: 100%;">
                        Entendi
                    </button>
                </div>
            `;
            document.body.appendChild(modal);
            modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
        }

        async function enviarAssinatura() {
            if (!temAssinatura) {
                alert('Por favor, desenhe sua assinatura.');
                return;
            }
            
            if (!selfieBase64) {
                alert('A selfie é obrigatória! Por favor, tire uma foto sua na Etapa 2.');
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
                        longitude: localizacao?.longitude,
                        aceite_termos: true,
                        timestamp_aceite: new Date().toISOString()
                    })
                });
                
                const data = await resp.json();
                
                if (data.sucesso) {
                    document.getElementById('conteudo').innerHTML = `
                        <div class="sucesso">
                            <h2>✅ Documento Assinado com Sucesso!</h2>
                            <p>Sua assinatura foi registrada em ${new Date().toLocaleString('pt-BR')}</p>
                            <div style="margin-top: 25px; display: flex; flex-direction: column; gap: 15px; align-items: center;">
                                <a href="/api/documento/${token}/download" class="btn btn-primario" style="text-decoration: none; display: inline-block; padding: 12px 25px;">
                                    📄 Baixar Documento Original
                                </a>
                                <a href="/api/pdf_assinado_por_token/${token}" class="btn btn-sucesso" style="text-decoration: none; display: inline-block; padding: 12px 25px;">
                                    ✅ Baixar Documento Assinado
                                </a>
                            </div>
                            <p style="margin-top: 20px; color: #aaa; font-size: 14px;">Você pode fechar esta página ou baixar os documentos acima.</p>
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

@app.route('/api/documento/<token>/download')
def download_documento_original(token):
    """Download do documento original (não assinado) pelo token do signatário"""
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
        
        # Decodificar base64 para bytes
        pdf_data = base64.b64decode(row['arquivo_base64'])
        
        return Response(
            pdf_data,
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="{row["arquivo_nome"]}"'}
        )
        
    except Exception as e:
        return f'Erro: {str(e)}', 500

@app.route('/api/pdf_assinado_por_token/<token>')
def download_pdf_assinado_por_token(token):
    """Download do PDF assinado pelo token do signatário"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Buscar doc_id pelo token
        cur.execute('SELECT doc_id FROM signatarios WHERE token = %s', (token,))
        row = cur.fetchone()
        
        if not row:
            cur.close()
            conn.close()
            return 'Token inválido', 404
        
        doc_id = row['doc_id']
        cur.close()
        conn.close()
        
        # Redirecionar para o endpoint existente de PDF assinado
        return redirect(f'/api/pdf_assinado/{doc_id}')
        
    except Exception as e:
        return f'Erro: {str(e)}', 500

@app.route('/api/assinar', methods=['POST'])
def assinar():
    """Processa a assinatura com selfie, localização, aceite de termos e auditoria"""
    try:
        data = request.json
        token = data.get('token')
        assinatura_base64 = data.get('assinatura')
        selfie_base64 = data.get('selfie')
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        aceite_termos = True  # Aceite implícito: ao assinar, usuário aceita os termos
        timestamp_aceite = data.get('timestamp_aceite') or datetime.now(BRT).isoformat()
        
        if not token or not assinatura_base64:
            return jsonify({'erro': 'Dados incompletos'})
        
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('SELECT s.*, d.doc_id FROM signatarios s JOIN documentos d ON s.doc_id = d.doc_id WHERE s.token = %s', (token,))
        row = cur.fetchone()
        
        if not row:
            cur.close()
            conn.close()
            return jsonify({'erro': 'Token inválido'})
        
        if row['assinado']:
            cur.close()
            conn.close()
            return jsonify({'erro': 'Documento já foi assinado'})
        
        # Obter IP real (considerando proxies como Render, Cloudflare, etc.)
        ip_real = request.headers.get('X-Forwarded-For', request.headers.get('X-Real-IP', request.remote_addr))
        if ip_real and ',' in ip_real:
            ip_real = ip_real.split(',')[0].strip()
        
        user_agent = request.headers.get('User-Agent', '')
        
        # Gerar hash do aceite de termos (evidência imutável)
        dados_aceite = f"{token}|{row['nome']}|{row['cpf']}|{aceite_termos}|{timestamp_aceite}|{ip_real}"
        hash_aceite = hashlib.sha256(dados_aceite.encode()).hexdigest()
        
        # Carimbo de tempo preciso (UTC e Brasil)
        timestamp_utc = datetime.now(timezone.utc)
        timestamp_brasil = agora_brasil()
        
        # Registrar assinatura com todos os dados incluindo aceite
        cur.execute('''
            UPDATE signatarios 
            SET assinado = TRUE, 
                assinatura_base64 = %s,
                selfie_base64 = %s,
                ip_assinatura = %s,
                data_assinatura = %s,
                user_agent = %s,
                latitude = %s,
                longitude = %s,
                aceite_termos = %s,
                data_aceite = %s,
                hash_aceite = %s
            WHERE token = %s
        ''', (
            assinatura_base64,
            selfie_base64,
            ip_real,
            timestamp_brasil,
            user_agent,
            latitude,
            longitude,
            aceite_termos,
            timestamp_brasil,
            hash_aceite,
            token
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        
        # Registrar no log de auditoria
        registrar_auditoria(
            doc_id=row['doc_id'],
            acao='ASSINATURA_CONCLUIDA',
            usuario=row['nome'],
            ip=ip_real,
            user_agent=user_agent,
            dados_adicionais={
                'signatario_id': row['id'],
                'cpf_mascarado': row['cpf'][:3] + '.***.***-' + row['cpf'][-2:] if row['cpf'] else None,
                'latitude': float(latitude) if latitude else None,
                'longitude': float(longitude) if longitude else None,
                'aceite_termos': aceite_termos,
                'hash_aceite': hash_aceite,
                'timestamp_utc': timestamp_utc.isoformat(),
                'timestamp_brasil': timestamp_brasil.isoformat()
            }
        )
        
        # Verificar se todos os signatários assinaram
        try:
            conn2 = get_db()
            cur2 = conn2.cursor()
            cur2.execute('''
                SELECT COUNT(*) as total, 
                       SUM(CASE WHEN assinado THEN 1 ELSE 0 END) as assinados
                FROM signatarios WHERE doc_id = %s
            ''', (row['doc_id'],))
            stats = cur2.fetchone()
            cur2.close()
            conn2.close()
            
            todos_assinaram = stats['total'] == stats['assinados']
            
            # Notificar criador do documento por email (assíncrono para evitar timeout)
            # Email individual a cada assinatura + email quando todos assinarem
            notificar_assinatura_async(row['doc_id'], row['nome'], todos_assinaram=False)
            
            if todos_assinaram:
                # Enviar email especial quando todos assinaram
                notificar_assinatura_async(row['doc_id'], row['nome'], todos_assinaram=True)
        except Exception as e:
            print(f"[EMAIL] Erro ao verificar/notificar: {e}")
        
        return jsonify({'sucesso': True})
        
    except Exception as e:
        return jsonify({'erro': str(e)})

# ==================== ENDPOINT TEMPORÁRIO DE LIMPEZA ====================
# REMOVER APÓS USO!
@app.route('/api/limpar_tudo', methods=['POST'])
def limpar_tudo():
    """ENDPOINT TEMPORÁRIO - Remove todos os documentos e signatários"""
    try:
        # Chave secreta para evitar uso não autorizado
        data = request.json or {}
        chave = data.get('chave', '')
        
        if chave != 'LIMPAR_DADOS_2024':
            return jsonify({'erro': 'Chave de segurança inválida'}), 403
        
        conn = get_db()
        cur = conn.cursor()
        
        # Limpar na ordem correta (foreign keys)
        cur.execute("DELETE FROM signatarios")
        cur.execute("DELETE FROM documentos")
        cur.execute("DELETE FROM pastas WHERE id > 1")  # Manter pasta raiz
        
        # Resetar sequências
        cur.execute("ALTER SEQUENCE signatarios_id_seq RESTART WITH 1")
        cur.execute("ALTER SEQUENCE documentos_id_seq RESTART WITH 1")
        cur.execute("ALTER SEQUENCE pastas_id_seq RESTART WITH 2")
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'sucesso': True,
            'mensagem': 'Todos os dados foram limpos com sucesso!'
        })
        
    except Exception as e:
        return jsonify({'erro': str(e)})

@app.route('/api/validar_signatario', methods=['POST'])
def validar_signatario():
    """Valida CPF e data de nascimento do signatário antes de permitir assinatura"""
    try:
        data = request.json
        token = data.get('token')
        cpf_informado = data.get('cpf', '').replace('.', '').replace('-', '').strip()
        data_nascimento_informada = data.get('data_nascimento', '').strip()
        
        if not token:
            return jsonify({'erro': 'Token não informado', 'valido': False})
        
        if not cpf_informado or not data_nascimento_informada:
            return jsonify({'erro': 'CPF e data de nascimento são obrigatórios', 'valido': False})
        
        # Validar formato e dígitos verificadores do CPF
        cpf_valido, msg_cpf = validar_cpf(cpf_informado)
        if not cpf_valido:
            return jsonify({'erro': msg_cpf, 'valido': False})
        
        conn = get_db()
        cur = conn.cursor()
        
        # Buscar dados cadastrados do signatário
        cur.execute('''
            SELECT s.cpf, s.data_nascimento, s.nome, s.assinado, d.doc_id
            FROM signatarios s
            JOIN documentos d ON s.doc_id = d.doc_id
            WHERE s.token = %s
        ''', (token,))
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if not row:
            return jsonify({'erro': 'Token inválido', 'valido': False})
        
        if row['assinado']:
            return jsonify({'erro': 'Este documento já foi assinado', 'valido': False})
        
        # Comparar CPF (remover formatação)
        cpf_cadastrado = (row['cpf'] or '').replace('.', '').replace('-', '').strip()
        
        if cpf_informado != cpf_cadastrado:
            return jsonify({
                'erro': 'CPF não confere com o cadastro. Verifique os dados informados.',
                'valido': False
            })
        
        # Comparar data de nascimento
        data_cadastrada = row['data_nascimento']
        
        if data_cadastrada:
            # Converter para string no formato YYYY-MM-DD
            if hasattr(data_cadastrada, 'strftime'):
                data_cadastrada_str = data_cadastrada.strftime('%Y-%m-%d')
            else:
                data_cadastrada_str = str(data_cadastrada)
            
            # Normalizar data informada (pode vir como DD/MM/YYYY ou YYYY-MM-DD)
            data_informada_normalizada = data_nascimento_informada
            if '/' in data_nascimento_informada:
                partes = data_nascimento_informada.split('/')
                if len(partes) == 3:
                    data_informada_normalizada = f"{partes[2]}-{partes[1]}-{partes[0]}"
            
            if data_informada_normalizada != data_cadastrada_str:
                return jsonify({
                    'erro': 'Data de nascimento não confere com o cadastro. Verifique os dados informados.',
                    'valido': False
                })
        
        # Obter IP para auditoria
        ip_real = request.headers.get('X-Forwarded-For', request.headers.get('X-Real-IP', request.remote_addr))
        if ip_real and ',' in ip_real:
            ip_real = ip_real.split(',')[0].strip()
        
        # Registrar auditoria de validação
        registrar_auditoria(
            doc_id=row['doc_id'],
            acao='IDENTIDADE_VALIDADA',
            usuario=row['nome'],
            ip=ip_real,
            user_agent=request.headers.get('User-Agent', ''),
            dados_adicionais={
                'cpf_mascarado': cpf_informado[:3] + '.***.***-' + cpf_informado[-2:],
                'validacao_sucesso': True
            }
        )
        
        return jsonify({
            'valido': True,
            'nome': row['nome'],
            'mensagem': 'Dados validados com sucesso!'
        })
        
    except Exception as e:
        return jsonify({'erro': str(e), 'valido': False})

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
        email_criador = data.get('email_criador', '')  # Email do usuário que criou o documento
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
        
        # Inserir documento com hash, pasta_id e email_criador
        cur.execute('''
            INSERT INTO documentos (doc_id, titulo, arquivo_nome, arquivo_base64, arquivo_hash, criado_por, pasta_id, email_criador)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (doc_id, titulo, arquivo_nome, arquivo_base64, arquivo_hash, criado_por, pasta_id, email_criador))
        
        # Inserir signatários
        links = []
        for sig in signatarios:
            token = hashlib.sha256(f"{doc_id}{sig['nome']}{datetime.now().isoformat()}".encode()).hexdigest()[:32]
            
            # Tratar data_nascimento vazia ou inválida
            data_nasc = sig.get('data_nascimento', '')
            if data_nasc and data_nasc.strip():
                # Tentar converter formato DD/MM/YYYY para YYYY-MM-DD (PostgreSQL)
                try:
                    if '/' in data_nasc:
                        partes = data_nasc.strip().split('/')
                        if len(partes) == 3:
                            data_nasc = f"{partes[2]}-{partes[1]}-{partes[0]}"
                except:
                    data_nasc = None
            else:
                data_nasc = None
            
            cur.execute('''
                INSERT INTO signatarios (doc_id, nome, email, cpf, telefone, token, data_nascimento)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (doc_id, sig.get('nome', ''), sig.get('email', ''), sig.get('cpf', ''), sig.get('telefone', ''), token, data_nasc))
            
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
        
        # Registrar auditoria de criação de documento
        ip_real = request.headers.get('X-Forwarded-For', request.headers.get('X-Real-IP', request.remote_addr))
        if ip_real and ',' in ip_real:
            ip_real = ip_real.split(',')[0].strip()
        
        registrar_auditoria(
            doc_id=doc_id,
            acao='DOCUMENTO_CRIADO',
            usuario=criado_por,
            ip=ip_real,
            user_agent=request.headers.get('User-Agent', ''),
            dados_adicionais={
                'titulo': titulo,
                'arquivo_nome': arquivo_nome,
                'arquivo_hash': arquivo_hash,
                'total_signatarios': len(signatarios),
                'pasta_id': pasta_id
            }
        )
        
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
    """Gera e retorna PDF com assinaturas aplicadas - Layout melhorado"""
    try:
        from io import BytesIO
        from PyPDF2 import PdfReader, PdfWriter
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        from reportlab.lib.colors import HexColor
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
        
        # Buscar signatários que assinaram (incluindo todos os campos)
        cur.execute('''
            SELECT nome, email, cpf, telefone, token, assinado, assinatura_base64, selfie_base64,
                   data_assinatura, ip_assinatura, user_agent, latitude, longitude, endereco_aproximado
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
        
        # Cores
        cor_titulo = HexColor('#1a1a1a')
        cor_label = HexColor('#666666')
        cor_valor = HexColor('#000000')
        cor_linha = HexColor('#cccccc')
        cor_fundo_imagem = HexColor('#f5f5f5')
        
        # Cabeçalho com título
        c.setFillColor(cor_titulo)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, height - 50, "FOLHA DE ASSINATURAS DIGITAIS")
        
        # Informações do documento
        c.setFillColor(cor_label)
        c.setFont("Helvetica", 10)
        c.drawString(50, height - 75, "Documento:")
        c.setFillColor(cor_valor)
        c.drawString(120, height - 75, f"{doc['titulo'] or doc['arquivo_nome']}")
        
        c.setFillColor(cor_label)
        c.drawString(50, height - 90, "Hash SHA-256:")
        c.setFillColor(cor_valor)
        c.setFont("Helvetica", 8)
        c.drawString(130, height - 90, f"{doc['arquivo_hash']}")
        
        c.setFont("Helvetica", 10)
        c.setFillColor(cor_label)
        c.drawString(50, height - 105, "Criado em:")
        c.setFillColor(cor_valor)
        criado_str = doc['criado_em'].strftime('%d/%m/%Y às %H:%M:%S') if doc['criado_em'] else ''
        c.drawString(115, height - 105, criado_str)
        
        c.setFillColor(cor_label)
        c.drawString(50, height - 120, "Última atualização em:")
        c.setFillColor(cor_valor)
        c.drawString(175, height - 120, agora_brasil().strftime('%d/%m/%Y às %H:%M:%S'))
        
        # Linha separadora
        c.setStrokeColor(cor_linha)
        c.setLineWidth(1)
        c.line(50, height - 135, width - 50, height - 135)
        
        # Posição inicial para assinaturas
        y_pos = height - 160
        
        for idx, sig in enumerate(signatarios):
            if sig['assinado']:
                # Verificar se precisa de nova página (altura estimada ~450-500px por signatário)
                if y_pos < 500:
                    c.showPage()
                    y_pos = height - 50
                
                # Box do signatário - será desenhado após calcular altura necessária
                c.setStrokeColor(cor_linha)
                c.setLineWidth(0.5)
                box_start_y = y_pos  # Guardar posição inicial
                # NÃO desenhar o box aqui - desenhar depois de saber a altura
                
                # Nome do signatário (título do box)
                c.setFillColor(cor_titulo)
                c.setFont("Helvetica-Bold", 12)
                c.drawString(60, y_pos - 20, f"Signatário: {sig['nome']}")
                
                # Informações textuais - coluna esquerda
                col_x = 60
                info_y = y_pos - 40
                
                c.setFont("Helvetica", 9)
                
                # Email
                if sig['email']:
                    c.setFillColor(cor_label)
                    c.drawString(col_x, info_y, "Email:")
                    c.setFillColor(cor_valor)
                    c.drawString(col_x + 40, info_y, sig['email'])
                    info_y -= 14
                
                # CPF
                if sig['cpf']:
                    c.setFillColor(cor_label)
                    c.drawString(col_x, info_y, "CPF:")
                    c.setFillColor(cor_valor)
                    c.drawString(col_x + 40, info_y, sig['cpf'])
                    info_y -= 14
                
                # Telefone
                if sig.get('telefone'):
                    c.setFillColor(cor_label)
                    c.drawString(col_x, info_y, "Telefone:")
                    c.setFillColor(cor_valor)
                    c.drawString(col_x + 55, info_y, sig['telefone'])
                    info_y -= 14
                
                # Data e hora da assinatura
                if sig['data_assinatura']:
                    c.setFillColor(cor_label)
                    c.drawString(col_x, info_y, "Data e hora da assinatura:")
                    c.setFillColor(cor_valor)
                    data_str = sig['data_assinatura'].strftime('%d/%m/%Y às %H:%M:%S')
                    c.drawString(col_x + 140, info_y, data_str)
                    info_y -= 14
                
                # Token
                if sig.get('token'):
                    c.setFillColor(cor_label)
                    c.drawString(col_x, info_y, "Token:")
                    c.setFillColor(cor_valor)
                    c.setFont("Helvetica", 7)
                    c.drawString(col_x + 40, info_y, sig['token'])
                    c.setFont("Helvetica", 9)
                    info_y -= 14
                
                # IP (usar X-Forwarded-For se disponível, senão ip_assinatura)
                ip_real = sig['ip_assinatura'] or 'Não disponível'
                c.setFillColor(cor_label)
                c.drawString(col_x, info_y, "IP do dispositivo:")
                c.setFillColor(cor_valor)
                c.drawString(col_x + 95, info_y, ip_real)
                info_y -= 14
                
                # Dispositivo (User Agent) - texto maior, múltiplas linhas se necessário
                if sig.get('user_agent'):
                    c.setFillColor(cor_label)
                    c.drawString(col_x, info_y, "Dispositivo:")
                    c.setFillColor(cor_valor)
                    c.setFont("Helvetica", 7)
                    
                    # Quebrar user agent em múltiplas linhas se necessário
                    ua = sig['user_agent']
                    max_chars_per_line = 90
                    
                    if len(ua) <= max_chars_per_line:
                        c.drawString(col_x + 60, info_y, ua)
                        info_y -= 12
                    else:
                        # Primeira linha
                        c.drawString(col_x + 60, info_y, ua[:max_chars_per_line])
                        info_y -= 10
                        # Segunda linha (continuação)
                        if len(ua) > max_chars_per_line:
                            c.drawString(col_x + 60, info_y, ua[max_chars_per_line:max_chars_per_line*2])
                            info_y -= 10
                        # Terceira linha se necessário
                        if len(ua) > max_chars_per_line * 2:
                            c.drawString(col_x + 60, info_y, ua[max_chars_per_line*2:])
                            info_y -= 10
                    
                    c.setFont("Helvetica", 9)
                    info_y -= 4
                
                # Localização
                if sig['latitude'] and sig['longitude']:
                    c.setFillColor(cor_label)
                    c.drawString(col_x, info_y, "Localização aproximada:")
                    c.setFillColor(cor_valor)
                    loc = f"{sig['latitude']}, {sig['longitude']}"
                    if sig.get('endereco_aproximado'):
                        loc = sig['endereco_aproximado']
                    c.drawString(col_x + 125, info_y, loc[:60])
                    info_y -= 14
                
                # Linha separadora antes das imagens - posição baseada no último texto
                c.setStrokeColor(cor_linha)
                c.setLineWidth(0.5)
                # Usar info_y que já está posicionado após o último texto
                images_y = info_y - 10
                c.line(60, images_y, width - 60, images_y)
                
                # Título da seção de imagens
                c.setFillColor(cor_label)
                c.setFont("Helvetica-Bold", 9)
                c.drawString(60, images_y - 15, "Evidências de Identificação:")
                
                # Layout lado a lado: Selfie à esquerda, Assinatura à direita (mais perto da selfie)
                # Posição baseada no título da seção
                selfie_x = 70
                assinatura_x = 300  # Um pouco mais à direita
                img_y = images_y - 300  # Espaço para selfie 3/4 (260px altura + margem)
                
                # SELFIE - Maior (150x150) e melhor qualidade
                if sig['selfie_base64']:
                    try:
                        img_data = sig['selfie_base64']
                        if ',' in img_data:
                            img_data = img_data.split(',')[1]
                        
                        img_bytes = base64.b64decode(img_data)
                        img = Image.open(BytesIO(img_bytes))
                        
                        # Converter para RGB se necessário
                        if img.mode in ('RGBA', 'LA', 'P'):
                            background = Image.new('RGB', img.size, (255, 255, 255))
                            if img.mode == 'P':
                                img = img.convert('RGBA')
                            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                            img = background
                        elif img.mode != 'RGB':
                            img = img.convert('RGB')
                        
                        # Selfie formato 3:4 (proporção retrato) - 195x260
                        target_width = 195
                        target_height = 260
                        # Redimensionar mantendo proporção e cortando se necessário
                        img_ratio = img.width / img.height
                        target_ratio = target_width / target_height
                        
                        if img_ratio > target_ratio:
                            # Imagem mais larga - ajustar pela altura
                            new_height = target_height
                            new_width = int(target_height * img_ratio)
                        else:
                            # Imagem mais alta - ajustar pela largura
                            new_width = target_width
                            new_height = int(target_width / img_ratio)
                        
                        img = img.resize((new_width, new_height), Image.LANCZOS)
                        
                        # Cortar para 180x240 centralizado
                        left = (new_width - target_width) // 2
                        top = (new_height - target_height) // 2
                        img = img.crop((left, top, left + target_width, top + target_height))
                        
                        img_buffer = BytesIO()
                        img.save(img_buffer, format='JPEG', quality=95)
                        img_buffer.seek(0)
                        
                        # Desenhar fundo cinza claro
                        c.setFillColor(cor_fundo_imagem)
                        c.rect(selfie_x - 5, img_y - 5, img.width + 10, img.height + 10, stroke=0, fill=1)
                        
                        c.drawImage(ImageReader(img_buffer), selfie_x, img_y, 
                                   width=img.width, height=img.height)
                        
                        # Legenda da selfie
                        c.setFillColor(cor_label)
                        c.setFont("Helvetica", 8)
                        c.drawString(selfie_x, img_y - 15, "Foto de identificação (Selfie)")
                    except Exception as e:
                        c.setFillColor(cor_label)
                        c.setFont("Helvetica", 8)
                        c.drawString(selfie_x, img_y + 50, "Selfie não disponível")
                
                # ASSINATURA - Maior (250x100) com fundo branco
                if sig['assinatura_base64']:
                    try:
                        img_data = sig['assinatura_base64']
                        if ',' in img_data:
                            img_data = img_data.split(',')[1]
                        
                        img_bytes = base64.b64decode(img_data)
                        img = Image.open(BytesIO(img_bytes))
                        
                        # IMPORTANTE: Converter PNG com transparência para fundo branco
                        if img.mode in ('RGBA', 'LA', 'P'):
                            background = Image.new('RGB', img.size, (255, 255, 255))
                            if img.mode == 'P':
                                img = img.convert('RGBA')
                            if img.mode == 'RGBA':
                                background.paste(img, mask=img.split()[3])
                            else:
                                background.paste(img)
                            img = background
                        elif img.mode != 'RGB':
                            img = img.convert('RGB')
                        
                        # Assinatura - tamanho ajustado para caber na tabela
                        max_width = 437  # 380 + 15%
                        max_height = 138  # 120 + 15%
                        img.thumbnail((max_width, max_height), Image.LANCZOS)
                        
                        img_buffer = BytesIO()
                        img.save(img_buffer, format='PNG', quality=95)
                        img_buffer.seek(0)
                        
                        # Desenhar fundo branco para assinatura
                        c.setFillColor(HexColor('#ffffff'))
                        c.setStrokeColor(cor_linha)
                        c.rect(assinatura_x - 5, img_y + 50 - 5, img.width + 10, img.height + 10, stroke=1, fill=1)
                        
                        c.drawImage(ImageReader(img_buffer), assinatura_x, img_y + 50, 
                                   width=img.width, height=img.height)
                        
                        # Legenda
                        c.setFillColor(cor_label)
                        c.setFont("Helvetica", 8)
                        c.drawString(assinatura_x, img_y + 35, "Assinatura manuscrita digital")
                    except Exception as e:
                        c.setFillColor(cor_label)
                        c.setFont("Helvetica", 8)
                        c.drawString(assinatura_x, img_y + 50, "Assinatura não disponível")
                
                # ========== QR CODE DE VERIFICAÇÃO ==========
                # Gerar QR Code com link de verificação
                server_url = os.environ.get('RENDER_EXTERNAL_URL', 'https://signature-server-jq9j.onrender.com')
                verificacao_url = f"{server_url}/verificar/{doc_id}"
                
                try:
                    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=2)
                    qr.add_data(verificacao_url)
                    qr.make(fit=True)
                    qr_img = qr.make_image(fill_color="black", back_color="white")
                    
                    # Converter para bytes
                    qr_buffer = BytesIO()
                    qr_img.save(qr_buffer, format='PNG')
                    qr_buffer.seek(0)
                    
                    # ========== SEÇÃO DE VERIFICAÇÃO ==========
                    # Linha separadora
                    verif_y = img_y - 25
                    c.setStrokeColor(cor_linha)
                    c.setLineWidth(0.5)
                    c.line(60, verif_y, width - 60, verif_y)
                    
                    # Título da seção
                    c.setFillColor(cor_label)
                    c.setFont("Helvetica-Bold", 9)
                    c.drawString(60, verif_y - 15, "Verificação de Autenticidade:")
                    
                    # Box de fundo para QR e link
                    box_verif_y = verif_y - 110
                    c.setFillColor(HexColor('#f5f5f5'))
                    c.setStrokeColor(cor_linha)
                    c.rect(55, box_verif_y, width - 110, 90, stroke=1, fill=1)
                    
                    # QR Code à esquerda
                    qr_size = 70
                    qr_x = 70
                    qr_y = box_verif_y + 10
                    c.drawImage(ImageReader(qr_buffer), qr_x, qr_y, width=qr_size, height=qr_size)
                    
                    # Texto explicativo à direita do QR
                    text_x = qr_x + qr_size + 20
                    c.setFillColor(HexColor('#333333'))
                    c.setFont("Helvetica-Bold", 9)
                    c.drawString(text_x, qr_y + 60, "Escaneie o QR Code ou acesse o link:")
                    
                    # Link clicável (URL completa)
                    c.setFillColor(HexColor('#1565c0'))
                    c.setFont("Helvetica", 8)
                    c.drawString(text_x, qr_y + 45, verificacao_url)
                    
                    # Instruções
                    c.setFillColor(HexColor('#666666'))
                    c.setFont("Helvetica", 7)
                    c.drawString(text_x, qr_y + 25, "Este link permite verificar a autenticidade")
                    c.drawString(text_x, qr_y + 14, "deste documento e das assinaturas.")
                    
                    # Atualizar img_y para o cálculo do box incluir a verificação
                    img_y = box_verif_y - 10
                    
                except Exception as e:
                    # Se falhar o QR, continua sem ele
                    pass
                
                # Calcular altura final do box e desenhá-lo
                box_end_y = img_y - 20  # Margem inferior
                box_height = box_start_y - box_end_y
                c.setStrokeColor(cor_linha)
                c.setLineWidth(0.5)
                c.rect(50, box_end_y, width - 100, box_height, stroke=1, fill=0)
                
                y_pos = box_end_y - 20  # Próximo signatário
        
        # Rodapé com texto legal
        c.setFillColor(cor_label)
        c.setFont("Helvetica", 8)
        
        # Linha separadora do rodapé
        c.setStrokeColor(cor_linha)
        c.line(50, 60, width - 50, 60)
        
        # Texto legal
        c.drawString(50, 45, "Assinaturas eletrônicas e físicas têm igual validade legal, conforme MP 2.200-2/2001 e Lei 14.063/2020.")
        c.drawString(50, 33, "Documento assinado digitalmente via HAMI ERP - Sistema de Assinaturas Digitais")
        c.drawString(50, 21, f"Gerado em: {agora_brasil().strftime('%d/%m/%Y às %H:%M:%S')} (Horário de Brasília)")
        
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

# ==================== VERIFICAÇÃO DE AUTENTICIDADE ====================

PAGINA_VERIFICACAO = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verificação de Autenticidade - HAMI ERP</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
            padding: 10px;
        }
        .container {
            max-width: 700px;
            margin: 0 auto;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            padding: 20px;
            backdrop-filter: blur(10px);
            width: 100%;
        }
        h1 { 
            color: #4fc3f7; 
            margin-bottom: 10px; 
            text-align: center; 
            font-size: clamp(1.3rem, 5vw, 1.8rem);
        }
        .status-valido {
            background: linear-gradient(135deg, #1b5e20, #2e7d32);
            padding: 15px;
            border-radius: 15px;
            text-align: center;
            margin: 15px 0;
        }
        .status-valido h2 { 
            color: #81c784; 
            font-size: clamp(1.2rem, 4vw, 1.6rem);
        }
        .status-valido p { font-size: 0.9rem; }
        .info-doc {
            background: rgba(0,0,0,0.2);
            border-radius: 10px;
            padding: 15px;
            margin: 12px 0;
        }
        .info-doc h3 { 
            color: #4fc3f7; 
            margin-bottom: 12px; 
            border-bottom: 1px solid #333; 
            padding-bottom: 8px; 
            font-size: clamp(0.95rem, 3vw, 1.1rem);
        }
        .info-row { 
            display: flex; 
            flex-wrap: wrap;
            margin: 8px 0; 
            gap: 5px;
        }
        .info-label { 
            color: #aaa; 
            min-width: 100px;
            flex-shrink: 0; 
            font-size: 0.9rem;
        }
        .info-valor { 
            color: #fff; 
            word-break: break-word;
            flex: 1;
            font-size: 0.9rem;
        }
        .signatario {
            background: rgba(76, 175, 80, 0.1);
            border: 1px solid #4caf50;
            border-radius: 10px;
            padding: 12px;
            margin: 10px 0;
        }
        .signatario.pendente {
            background: rgba(255, 152, 0, 0.1);
            border-color: #ff9800;
        }
        .footer { 
            text-align: center; 
            margin-top: 15px; 
            color: #666; 
            font-size: 11px; 
        }
        
        /* Responsividade Mobile */
        @media (max-width: 480px) {
            body { padding: 8px; }
            .container { 
                padding: 15px; 
                border-radius: 15px;
            }
            .info-row { 
                flex-direction: column; 
                gap: 2px;
            }
            .info-label { 
                min-width: auto; 
                font-size: 0.85rem;
            }
            .info-valor { 
                font-size: 0.85rem;
                padding-left: 5px;
            }
            .status-valido { 
                padding: 12px; 
                margin: 10px 0;
            }
            .signatario { padding: 10px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 Verificação de Autenticidade</h1>
        <div id="conteudo">Carregando...</div>
    </div>
    <script>
        async function verificar() {
            const docId = window.location.pathname.split('/').pop();
            try {
                const resp = await fetch('/api/verificar_dados/' + docId);
                const data = await resp.json();
                
                if (data.erro) {
                    document.getElementById('conteudo').innerHTML = `
                        <div style="text-align: center; color: #f44336; padding: 40px;">
                            <h2>❌ Documento Não Encontrado</h2>
                            <p>Este documento não existe ou foi removido.</p>
                        </div>
                    `;
                    return;
                }
                
                let signatariosHtml = '';
                data.signatarios.forEach(sig => {
                    const classe = sig.assinado ? 'signatario' : 'signatario pendente';
                    const status = sig.assinado ? '✅ Assinado' : '⏳ Pendente';
                    signatariosHtml += `
                        <div class="${classe}">
                            <div class="info-row"><span class="info-label">Nome:</span><span class="info-valor">${sig.nome}</span></div>
                            <div class="info-row"><span class="info-label">CPF:</span><span class="info-valor">${sig.cpf}</span></div>
                            <div class="info-row"><span class="info-label">Status:</span><span class="info-valor">${status}</span></div>
                            ${sig.assinado ? `<div class="info-row"><span class="info-label">Data/Hora:</span><span class="info-valor">${sig.data_assinatura}</span></div>` : ''}
                            ${sig.assinado ? `<div class="info-row"><span class="info-label">IP:</span><span class="info-valor">${sig.ip}</span></div>` : ''}
                        </div>
                    `;
                });
                
                document.getElementById('conteudo').innerHTML = `
                    <div class="status-valido">
                        <h2>✅ DOCUMENTO AUTÊNTICO</h2>
                        <p>Este documento foi registrado no sistema HAMI ERP</p>
                    </div>
                    
                    <div class="info-doc">
                        <h3>📄 Informações do Documento</h3>
                        <div class="info-row"><span class="info-label">Título:</span><span class="info-valor">${data.titulo}</span></div>
                        <div class="info-row"><span class="info-label">Arquivo:</span><span class="info-valor">${data.arquivo_nome}</span></div>
                        <div class="info-row"><span class="info-label">Hash SHA-256:</span><span class="info-valor" style="font-size: 11px; word-break: break-all;">${data.hash}</span></div>
                        <div class="info-row"><span class="info-label">Criado em:</span><span class="info-valor">${data.criado_em}</span></div>
                    </div>
                    
                    <div class="info-doc">
                        <h3>👥 Signatários (${data.signatarios.length})</h3>
                        ${signatariosHtml}
                    </div>
                    
                    <div class="footer">
                        <p>Verificação realizada em ${new Date().toLocaleString('pt-BR')}</p>
                        <p>HAMI ERP - Sistema de Assinaturas Digitais</p>
                    </div>
                `;
            } catch (e) {
                document.getElementById('conteudo').innerHTML = `
                    <div style="text-align: center; color: #f44336; padding: 40px;">
                        <h2>❌ Erro de Conexão</h2>
                        <p>Não foi possível verificar o documento.</p>
                    </div>
                `;
            }
        }
        verificar();
    </script>
</body>
</html>
'''

@app.route('/verificar/<doc_id>')
def pagina_verificacao(doc_id):
    """Página de verificação de autenticidade do documento"""
    return render_template_string(PAGINA_VERIFICACAO)

@app.route('/api/verificar_dados/<doc_id>')
def verificar_dados(doc_id):
    """Retorna dados do documento para verificação"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Buscar documento
        cur.execute('''
            SELECT titulo, arquivo_nome, arquivo_hash, criado_em
            FROM documentos WHERE doc_id = %s
        ''', (doc_id,))
        
        doc = cur.fetchone()
        if not doc:
            cur.close()
            conn.close()
            return jsonify({'erro': 'Documento não encontrado'})
        
        # Buscar signatários
        cur.execute('''
            SELECT nome, cpf, assinado, data_assinatura, ip_assinatura
            FROM signatarios WHERE doc_id = %s
        ''', (doc_id,))
        
        sigs = cur.fetchall()
        cur.close()
        conn.close()
        
        signatarios = []
        for sig in sigs:
            signatarios.append({
                'nome': sig['nome'],
                'cpf': sig['cpf'][:3] + '.***.***-' + sig['cpf'][-2:] if sig['cpf'] else '',  # Mascarar CPF
                'assinado': sig['assinado'],
                'data_assinatura': sig['data_assinatura'].strftime('%d/%m/%Y às %H:%M:%S') if sig['data_assinatura'] else '',
                'ip': sig['ip_assinatura'] or ''
            })
        
        return jsonify({
            'titulo': doc['titulo'],
            'arquivo_nome': doc['arquivo_nome'],
            'hash': doc['arquivo_hash'],
            'criado_em': doc['criado_em'].strftime('%d/%m/%Y às %H:%M:%S') if doc['criado_em'] else '',
            'signatarios': signatarios
        })
        
    except Exception as e:
        return jsonify({'erro': str(e)})

# ==================== LIMPEZA DE DOCUMENTOS ====================

@app.route('/api/limpar_documentos', methods=['POST'])
def limpar_documentos():
    """Remove todos os documentos e signatários vinculados, mantém pastas"""
    try:
        data = request.json or {}
        chave = data.get('chave_confirmacao', '')
        
        # Chave de segurança para evitar limpeza acidental
        if chave != 'CONFIRMAR_LIMPEZA_HAMI':
            return jsonify({'erro': 'Chave de confirmação inválida'})
        
        conn = get_db()
        cur = conn.cursor()
        
        # Contar antes de deletar
        cur.execute('SELECT COUNT(*) as count FROM documentos')
        total_docs = cur.fetchone()['count']
        
        cur.execute('SELECT COUNT(*) as count FROM signatarios')
        total_sigs = cur.fetchone()['count']
        
        # Deletar signatários vinculados aos documentos
        cur.execute('DELETE FROM signatarios')
        
        # Deletar documentos
        cur.execute('DELETE FROM documentos')
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'sucesso': True,
            'documentos_removidos': total_docs,
            'signatarios_removidos': total_sigs
        })
        
    except Exception as e:
        return jsonify({'erro': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
