# HAMI ERP - Servidor de Assinaturas Digitais

Servidor para assinaturas digitais integrado ao HAMI ERP.

## Deploy no Render.com

1. Crie uma conta em [render.com](https://render.com)
2. Clique em "New" → "Web Service"
3. Conecte seu repositório GitHub
4. O Render detectará automaticamente as configurações

## Banco de Dados

Crie um banco PostgreSQL gratuito no Render:
1. Dashboard → "New" → "PostgreSQL"
2. Copie a URL de conexão
3. Adicione como variável de ambiente `DATABASE_URL`

## Variáveis de Ambiente

- `DATABASE_URL`: URL de conexão do PostgreSQL (fornecida pelo Render)

## Endpoints

- `GET /` - Página inicial
- `GET /health` - Health check
- `GET /assinar/<token>` - Página de assinatura
- `POST /api/criar_documento` - Criar novo documento
- `GET /api/status/<doc_id>` - Status das assinaturas
- `GET /api/documentos` - Listar documentos
