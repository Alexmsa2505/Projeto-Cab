-- =============================================================================
-- Code Wave: esquema PostgreSQL planejado (multi-tenant por barbearia_id)
--
-- Espelha app/models.py. Use como base para as migrações (Alembic) quando o
-- banco entrar no lugar de app/repositorios/memoria.py.
--
-- Garantias que ficam no próprio banco:
--   * toda linha pertence a uma barbearia (barbearia_id NOT NULL);
--   * chaves estrangeiras compostas impedem, por exemplo, que um agendamento
--     aponte para um barbeiro ou cliente de outra barbearia;
--   * a constraint de exclusão impede dois horários sobrepostos para o mesmo
--     barbeiro, mesmo com dois clientes confirmando ao mesmo tempo.
-- Datas sem fuso: horário local da barbearia (coluna fuso_horario).
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ---------------------------------------------------------------- barbearias
CREATE TABLE barbearias (
    id                          bigserial PRIMARY KEY,
    slug                        varchar(40)  NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    nome                        varchar(80)  NOT NULL,
    whatsapp                    varchar(20)  NOT NULL DEFAULT '',
    endereco                    varchar(160) NOT NULL DEFAULT '',
    logo_url                    text,
    cor_primaria                char(7)      NOT NULL DEFAULT '#B98B2F' CHECK (cor_primaria ~ '^#[0-9A-Fa-f]{6}$'),
    cor_secundaria              char(7)      NOT NULL DEFAULT '#173A30' CHECK (cor_secundaria ~ '^#[0-9A-Fa-f]{6}$'),
    fuso_horario                varchar(64)  NOT NULL DEFAULT 'America/Sao_Paulo',
    abre_as                     time         NOT NULL DEFAULT '09:00',
    fecha_as                    time         NOT NULL DEFAULT '19:00',
    dias_funcionamento          smallint[]   NOT NULL DEFAULT '{0,1,2,3,4,5}',  -- 0 = segunda
    intervalo_minutos           smallint     NOT NULL DEFAULT 30 CHECK (intervalo_minutos IN (15, 20, 30, 45, 60)),
    antecedencia_minima_minutos integer      NOT NULL DEFAULT 60 CHECK (antecedencia_minima_minutos BETWEEN 0 AND 2880),
    janela_agendamento_dias     smallint     NOT NULL DEFAULT 14 CHECK (janela_agendamento_dias BETWEEN 1 AND 90),
    lembrete_horas_antes        smallint     NOT NULL DEFAULT 3  CHECK (lembrete_horas_antes BETWEEN 1 AND 48),
    dias_inatividade            smallint     NOT NULL DEFAULT 30 CHECK (dias_inatividade BETWEEN 7 AND 365),
    mensagem_reativacao         text         NOT NULL,
    criado_em                   timestamp    NOT NULL DEFAULT now(),
    CHECK (fecha_as > abre_as)
);

-- ------------------------------------------------------------------ serviços
CREATE TABLE servicos (
    id               bigserial PRIMARY KEY,
    barbearia_id     bigint      NOT NULL REFERENCES barbearias (id) ON DELETE CASCADE,
    nome             varchar(40) NOT NULL,
    preco_centavos   integer     NOT NULL CHECK (preco_centavos >= 0),
    duracao_minutos  smallint    NOT NULL CHECK (duracao_minutos BETWEEN 5 AND 480),
    ativo            boolean     NOT NULL DEFAULT true,
    ordem            smallint    NOT NULL DEFAULT 0
);
CREATE INDEX servicos_barbearia ON servicos (barbearia_id, ordem);

-- ----------------------------------------------------------------- barbeiros
CREATE TABLE barbeiros (
    id                   bigserial PRIMARY KEY,
    barbearia_id         bigint      NOT NULL REFERENCES barbearias (id) ON DELETE CASCADE,
    nome                 varchar(80) NOT NULL,
    especialidade        varchar(80) NOT NULL DEFAULT '',
    comissao_percentual  smallint    NOT NULL DEFAULT 50 CHECK (comissao_percentual BETWEEN 0 AND 100),
    ativo                boolean     NOT NULL DEFAULT true,
    UNIQUE (barbearia_id, id)
);

-- Portfólio (no código: Barbeiro.fotos, até 2 por profissional)
CREATE TABLE barbeiro_fotos (
    id            bigserial PRIMARY KEY,
    barbearia_id  bigint   NOT NULL,
    barbeiro_id   bigint   NOT NULL,
    url           text     NOT NULL,
    ordem         smallint NOT NULL DEFAULT 0 CHECK (ordem BETWEEN 0 AND 1),
    UNIQUE (barbeiro_id, ordem),
    FOREIGN KEY (barbearia_id, barbeiro_id) REFERENCES barbeiros (barbearia_id, id) ON DELETE CASCADE
);

-- ------------------------------------------------------------------ clientes
CREATE TABLE clientes (
    id                  bigserial PRIMARY KEY,
    barbearia_id        bigint      NOT NULL REFERENCES barbearias (id) ON DELETE CASCADE,
    nome                varchar(80) NOT NULL,
    telefone            varchar(20) NOT NULL,                -- E.164: +5511987654321
    canal_preferido     varchar(10) NOT NULL DEFAULT 'whatsapp' CHECK (canal_preferido IN ('whatsapp', 'sms')),
    criado_em           timestamp   NOT NULL DEFAULT now(),
    ultima_campanha_em  timestamp,
    UNIQUE (barbearia_id, telefone),                         -- o cliente é identificado pelo celular
    UNIQUE (barbearia_id, id)
);

-- -------------------------------------------------------------- agendamentos
CREATE TABLE agendamentos (
    id                   bigserial PRIMARY KEY,
    barbearia_id         bigint      NOT NULL REFERENCES barbearias (id) ON DELETE CASCADE,
    cliente_id           bigint      NOT NULL,
    barbeiro_id          bigint      NOT NULL,
    inicio               timestamp   NOT NULL,
    fim                  timestamp   NOT NULL,
    valor_centavos       integer     NOT NULL CHECK (valor_centavos >= 0),
    status               varchar(20) NOT NULL DEFAULT 'agendado'
                         CHECK (status IN ('agendado', 'confirmado', 'concluido', 'nao_compareceu', 'cancelado')),
    token                varchar(32) NOT NULL UNIQUE,         -- link de gestão do cliente
    canal                varchar(10) NOT NULL DEFAULT 'whatsapp' CHECK (canal IN ('whatsapp', 'sms')),
    criado_em            timestamp   NOT NULL DEFAULT now(),
    remarcado_em         timestamp,
    lembrete_enviado_em  timestamp,
    confirmado_em        timestamp,
    cancelado_em         timestamp,
    concluido_em         timestamp,
    comissao_percentual  smallint CHECK (comissao_percentual BETWEEN 0 AND 100),  -- congelada na conclusão
    CHECK (fim > inicio),
    FOREIGN KEY (barbearia_id, cliente_id)  REFERENCES clientes  (barbearia_id, id),
    FOREIGN KEY (barbearia_id, barbeiro_id) REFERENCES barbeiros (barbearia_id, id),
    -- Dois horários do mesmo barbeiro nunca se sobrepõem (cancelados não contam)
    CONSTRAINT agendamentos_sem_sobreposicao
        EXCLUDE USING gist (barbeiro_id WITH =, tsrange(inicio, fim) WITH &&)
        WHERE (status <> 'cancelado')
);
CREATE INDEX agendamentos_agenda   ON agendamentos (barbearia_id, inicio);
CREATE INDEX agendamentos_cliente  ON agendamentos (barbearia_id, cliente_id, inicio);
CREATE INDEX agendamentos_lembrete ON agendamentos (inicio) WHERE status = 'agendado' AND lembrete_enviado_em IS NULL;

-- Serviços do agendamento com preço da época (no código: Agendamento.itens)
CREATE TABLE agendamento_itens (
    id               bigserial PRIMARY KEY,
    agendamento_id   bigint      NOT NULL REFERENCES agendamentos (id) ON DELETE CASCADE,
    servico_id       bigint      REFERENCES servicos (id) ON DELETE SET NULL,
    nome             varchar(40) NOT NULL,
    preco_centavos   integer     NOT NULL CHECK (preco_centavos >= 0),
    duracao_minutos  smallint    NOT NULL
);
CREATE INDEX agendamento_itens_agendamento ON agendamento_itens (agendamento_id);

-- ----------------------------------------------------------------- bloqueios
CREATE TABLE bloqueios (
    id            bigserial PRIMARY KEY,
    barbearia_id  bigint      NOT NULL REFERENCES barbearias (id) ON DELETE CASCADE,
    barbeiro_id   bigint,                                    -- NULL = barbearia inteira
    inicio        timestamp   NOT NULL,
    fim           timestamp   NOT NULL,
    motivo        varchar(60) NOT NULL DEFAULT 'Pausa',
    criado_em     timestamp   NOT NULL DEFAULT now(),
    CHECK (fim > inicio),
    FOREIGN KEY (barbearia_id, barbeiro_id) REFERENCES barbeiros (barbearia_id, id) ON DELETE CASCADE
);
CREATE INDEX bloqueios_agenda ON bloqueios (barbearia_id, inicio);

-- ------------------------------------------------------------------ usuários
CREATE TABLE usuarios (
    id            bigserial PRIMARY KEY,
    barbearia_id  bigint       NOT NULL REFERENCES barbearias (id) ON DELETE CASCADE,
    nome          varchar(80)  NOT NULL,
    email         varchar(120) NOT NULL CHECK (email = lower(email)),
    senha_hash    text         NOT NULL,
    papel         varchar(10)  NOT NULL DEFAULT 'dono' CHECK (papel IN ('dono', 'barbeiro')),
    barbeiro_id   bigint       REFERENCES barbeiros (id) ON DELETE SET NULL,
    ativo         boolean      NOT NULL DEFAULT true,
    UNIQUE (barbearia_id, email)                             -- o login é por barbearia
);

-- ------------------------------------------------- código de 4 dígitos (curta duração)
CREATE TABLE verificacoes_telefone (
    id               bigserial PRIMARY KEY,
    barbearia_id     bigint      NOT NULL REFERENCES barbearias (id) ON DELETE CASCADE,
    token            varchar(32) NOT NULL UNIQUE,
    telefone         varchar(20) NOT NULL,
    canal            varchar(10) NOT NULL,
    codigo           char(4)     NOT NULL,
    dados            jsonb       NOT NULL,                    -- serviços, barbeiro e horário pedidos
    expira_em        timestamp   NOT NULL,
    ultimo_envio_em  timestamp   NOT NULL,
    tentativas       smallint    NOT NULL DEFAULT 0,
    criado_em        timestamp   NOT NULL DEFAULT now()
);
CREATE INDEX verificacoes_expiracao ON verificacoes_telefone (expira_em);   -- limpeza periódica

-- ------------------------------------------- mensagens (caixa de saída e auditoria)
CREATE TABLE mensagens (
    id              bigserial PRIMARY KEY,
    barbearia_id    bigint      NOT NULL REFERENCES barbearias (id) ON DELETE CASCADE,
    telefone        varchar(20) NOT NULL,
    canal           varchar(10) NOT NULL,
    tipo            varchar(20) NOT NULL
                    CHECK (tipo IN ('codigo', 'confirmacao', 'lembrete', 'remarcacao', 'cancelamento', 'reativacao')),
    texto           text        NOT NULL,
    status          varchar(10) NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'enviada', 'falhou')),
    erro            text,
    id_externo      varchar(80),
    cliente_id      bigint      REFERENCES clientes (id) ON DELETE SET NULL,
    agendamento_id  bigint      REFERENCES agendamentos (id) ON DELETE SET NULL,
    criado_em       timestamp   NOT NULL DEFAULT now(),
    enviado_em      timestamp
);
CREATE INDEX mensagens_caixa  ON mensagens (barbearia_id, criado_em DESC);
CREATE INDEX mensagens_limite ON mensagens (barbearia_id, telefone, tipo, criado_em);  -- limite de códigos por hora
