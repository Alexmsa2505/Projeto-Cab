document.addEventListener('DOMContentLoaded', () => {
    const checkboxesServicos = document.querySelectorAll('input[name="servico"]');
    const displayTotal = document.getElementById('valor-total');
    const form = document.getElementById('form-agendamento');

    // Atualiza o valor total em tempo real
    function atualizarTotal() {
        let total = 0;
        checkboxesServicos.forEach(checkbox => {
            if (checkbox.checked) {
                total += parseFloat(checkbox.getAttribute('data-preco'));
            }
        });
        displayTotal.textContent = total.toFixed(2).replace('.', ',');
    }

    checkboxesServicos.forEach(checkbox => {
        checkbox.addEventListener('change', atualizarTotal);
    });

    // Intercepta o formulário para enviar via AJAX/Fetch ao Python
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        
        // Verifica se pelo menos um serviço foi selecionado
        const servicosSelecionados = Array.from(checkboxesServicos).filter(c => c.checked);
        if (servicosSelecionados.length === 0) {
            alert('Por favor, selecione pelo menos um serviço.');
            return;
        }

        const formData = new FormData(form);
        const data = Object.fromEntries(formData.entries());
        data.servicos = servicosSelecionados.map(c => c.value);

        // Disparo para o backend Python
        fetch('/agendar', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if(result.status === "success") {
                // Aqui entraria o modal de validação anti-trote (código WhatsApp)
                alert('Tudo certo! Um código de 4 dígitos foi enviado para o seu WhatsApp.');
            }
        })
        .catch(error => {
            console.error('Erro:', error);
            alert('Erro ao processar o agendamento.');
        });
    });
});