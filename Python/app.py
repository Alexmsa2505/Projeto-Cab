from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

@app.route('/')
def index():
    # No futuro, aqui você fará a query no banco para buscar os dados 
    # da barbearia específica (cores, logo, barbeiros, serviços)
    barbearia_info = {
        "nome": "Barbearia Code Wave",
        "cor_primaria": "#1a1a1a",
        "cor_secundaria": "#d4af37" # Dourado
    }
    return render_template('index.html', barbearia=barbearia_info)

@app.route('/agendar', methods=['POST'])
def agendar():
    # Rota para receber os dados via fetch/AJAX e iniciar a validação WhatsApp
    dados = request.json
    # Lógica de salvar no banco e disparar validação via API (Twilio, Z-API, etc)
    return jsonify({"status": "success", "message": "Código de validação enviado!"})

if __name__ == '__main__':
    app.run(debug=True)