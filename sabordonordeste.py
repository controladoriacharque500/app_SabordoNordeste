import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import gspread
from gspread import service_account_from_dict

# -------------------------------------------------------------------
# CONFIGURAÇÃO E CONEXÃO
# -------------------------------------------------------------------
st.set_page_config(page_title="Gestão Minimercado", layout="wide")

@st.cache_resource
def conectar_google_sheets():
    try:
        if "gcp_service_account" in st.secrets:
            secrets_dict = dict(st.secrets["gcp_service_account"])
            private_key_corrompida = secrets_dict["private_key"]
            
            private_key_limpa = private_key_corrompida.replace('\n', '').replace(' ', '')
            private_key_limpa = private_key_limpa.replace('-----BEGINPRIVATEKEY-----', '').replace('-----ENDPRIVATEKEY-----', '')
            
            padding_necessario = len(private_key_limpa) % 4
            if padding_necessario != 0:
                private_key_limpa += '=' * (4 - padding_necessario)
            
            secrets_dict["private_key"] = f"-----BEGIN PRIVATE KEY-----\n{private_key_limpa}\n-----END PRIVATE KEY-----\n"
            
            gc = service_account_from_dict(secrets_dict)
            
            if "spreadsheet_url" in st.secrets:
                return gc.open_by_url(st.secrets["spreadsheet_url"])
            else:
                return gc.open("BD_Minimercado")
        else:
            st.error("O bloco 'gcp_service_account' não foi encontrado nos st.secrets!")
            return None
            
    except Exception as e:
        st.error(f"Erro crítico na autenticação do Google Sheets: {e}")
        return None

sh = conectar_google_sheets()

if not sh:
    st.stop()

def ler_aba(nome_aba):
    try:
        aba = sh.worksheet(nome_aba)
        dados = aba.get_all_records()
        return pd.DataFrame(dados)
    except gspread.exceptions.WorksheetNotFound:
        # Cria a aba automaticamente caso ela ainda não exista no Google Sheets
        sh.add_worksheet(title=nome_aba, rows="100", cols="20")
        return pd.DataFrame()

def atualizar_aba(nome_aba, df):
    aba = sh.worksheet(nome_aba)
    aba.clear()
    if not df.empty:
        aba.update([df.columns.values.tolist()] + df.astype(str).values.tolist())

# -------------------------------------------------------------------
# MENU LATERAL
# -------------------------------------------------------------------
st.title("🛒 Sistema de Gestão - Minimercado")

menu = st.sidebar.selectbox(
    "Navegação",
    [
        "PDV (Saída de Estoque)", 
        "Cadastro / Entrada de Estoque", 
        "Posição de Estoque", 
        "Gerenciar Produtos", 
        "Despesas Extras", 
        "Faturamento e Financeiro",
        "Fechamento Diário & Curva ABC"
    ]
)

# -------------------------------------------------------------------
# 1. PDV (VENDAS / CONSUMO / BONIFICAÇÃO)
# -------------------------------------------------------------------
if menu == "PDV (Saída de Estoque)":
    st.header("🛍️ Frente de Caixa e Saída de Estoque")
    
    df_produtos = ler_aba("Produtos_Estoque")
    
    if df_produtos.empty:
        st.info("Nenhum produto cadastrado no estoque.")
    else:
        df_produtos['Quantidade_Estoque'] = pd.to_numeric(df_produtos['Quantidade_Estoque'], errors='coerce').fillna(0.0)
        df_produtos['Preco_Venda'] = pd.to_numeric(df_produtos['Preco_Venda'], errors='coerce').fillna(0.0)
        df_produtos['Custo_Unitario'] = pd.to_numeric(df_produtos['Custo_Unitario'], errors='coerce').fillna(0.0)
        if 'Unidade_Medida' not in df_produtos.columns:
            df_produtos['Unidade_Medida'] = 'UN'
        
        produtos_disponiveis = df_produtos[df_produtos['Quantidade_Estoque'] > 0]
        
        if produtos_disponiveis.empty:
            st.warning("Não há produtos com estoque disponível.")
        else:
            tipo_operacao = st.radio("Tipo de Saída", ["🛒 Venda Normal", "🏠 Consumo Próprio / Uso Interno", "🎁 Bonificação / Cortesia"])
            
            produto_sel = st.selectbox("Selecione o Produto", produtos_disponiveis['Nome_Produto'].tolist())
            
            if produto_sel:
                item = df_produtos[df_produtos['Nome_Produto'] == produto_sel].iloc[0]
                unidade = str(item['Unidade_Medida']).upper()
                
                col_a, col_b, col_c = st.columns(3)
                col_a.write(f"**Preço Venda:** R$ {item['Preco_Venda']:.2f}")
                col_b.write(f"**Custo Unitário:** R$ {item['Custo_Unitario']:.2f}")
                col_c.write(f"**Estoque Disponível:** {item['Quantidade_Estoque']:.3f} {unidade}")
                
                if unidade in ['KG', 'L']:
                    qtd = st.number_input(
                        f"Quantidade em {unidade} (ex: 0.150 para 150g)", 
                        min_value=0.001, 
                        max_value=float(item['Quantidade_Estoque']), 
                        value=min(1.0, float(item['Quantidade_Estoque'])), 
                        step=0.050, 
                        format="%.3f"
                    )
                else:
                    qtd = st.number_input(
                        f"Quantidade em {unidade}", 
                        min_value=1, 
                        max_value=int(item['Quantidade_Estoque']), 
                        value=1, 
                        step=1
                    )
                
                if "Venda Normal" in tipo_operacao:
                    total_operacao = float(qtd) * float(item['Preco_Venda'])
                    st.subheader(f"Total a Cobrar: R$ {total_operacao:.2f}")
                else:
                    custo_total_consumo = float(qtd) * float(item['Custo_Unitario'])
                    st.warning(f"⚠️ **Saída sem cobrança.** Custo gerado para o caixa: **R$ {custo_total_consumo:.2f}**")
                    total_operacao = 0.0
                
                # Controle de trava contra duplo clique acidental
                if "processando_venda" not in st.session_state:
                    st.session_state.processando_venda = False

                if st.button("Confirmar Operação", type="primary", disabled=st.session_state.processando_venda):
                    st.session_state.processando_venda = True
                    
                    with st.spinner("Processando operação e atualizando estoque..."):
                        df_vendas = ler_aba("Vendas")
                        if 'Tipo_Saida' not in df_vendas.columns:
                            df_vendas['Tipo_Saida'] = "Venda Normal"
                            
                        nova_venda = pd.DataFrame([{
                            "ID_Venda": len(df_vendas) + 1,
                            "Data_Hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "ID_Produto": item['ID_Produto'],
                            "Nome_Produto": item['Nome_Produto'],
                            "Quantidade": qtd,
                            "Preco_Unitario": item['Preco_Venda'] if "Venda Normal" in tipo_operacao else 0.0,
                            "Valor_Total": total_operacao,
                            "Tipo_Saida": tipo_operacao
                        }])
                        df_vendas_atualizado = pd.concat([df_vendas, nova_venda], ignore_index=True)
                        atualizar_aba("Vendas", df_vendas_atualizado)
                        
                        if "Venda Normal" not in tipo_operacao:
                            df_despesas = ler_aba("Despesas_Extras")
                            nova_despesa = pd.DataFrame([{
                                "ID_Despesa": len(df_despesas) + 1,
                                "Data": datetime.now().strftime("%Y-%m-%d"),
                                "Categoria_Despesa": tipo_operacao.replace("🛒 ", "").replace("🏠 ", "").replace("🎁 ", ""),
                                "Descricao": f"Custo de {qtd} {unidade} de {item['Nome_Produto']}",
                                "Valor": float(qtd) * float(item['Custo_Unitario'])
                            }])
                            atualizar_aba("Despesas_Extras", pd.concat([df_despesas, nova_despesa], ignore_index=True))
                        
                        df_produtos.loc[df_produtos['Nome_Produto'] == produto_sel, 'Quantidade_Estoque'] -= qtd
                        atualizar_aba("Produtos_Estoque", df_produtos)
                    
                    st.session_state.processando_venda = False
                    st.success(f"✅ Operação '{tipo_operacao}' registrada com sucesso! ({qtd} {unidade} de {produto_sel})")
                    st.balloons()
                    st.rerun()

# -------------------------------------------------------------------
# 2. CADASTRO E ENTRADA DE ESTOQUE
# -------------------------------------------------------------------
elif menu == "Cadastro / Entrada de Estoque":
    st.header("📦 Alimentar / Cadastrar Estoque")
    
    df_produtos = ler_aba("Produtos_Estoque")
    
    opcao = st.radio("Ação", ["Novo Produto", "Adicionar Unidades / Peso a Produto Existente"])
    
    if opcao == "Novo Produto":
        col1, col2 = st.columns(2)
        with col1:
            nome = st.text_input("Nome do Produto")
            categoria = st.text_input("Categoria (ex: Bebidas, Mercearia, Frios)")
            unidade = st.selectbox("Unidade de Medida", ["UN", "KG", "L"])
        
        with col2:
            custo = st.number_input(f"Custo Unitário / por {unidade} (R$)", min_value=0.0, format="%.2f")
            preco = st.number_input(f"Preço de Venda Unitário / por {unidade} (R$)", min_value=0.0, format="%.2f")
            qtd_inicial = st.number_input(
                f"Quantidade Inicial em {unidade}", 
                min_value=0.0, 
                step=0.100 if unidade in ["KG", "L"] else 1.0, 
                format="%.3f" if unidade in ["KG", "L"] else "%.0f"
            )
            
        if st.button("Salvar Produto", type="primary"):
            if not nome.strip():
                st.error("⚠️ Por favor, informe o nome do produto antes de salvar.")
            elif preco <= 0.0 and custo <= 0.0:
                st.warning("⚠️ Preencha os valores de custo e preço de venda.")
            else:
                novo_id = int(pd.to_numeric(df_produtos['ID_Produto'], errors='coerce').max()) + 1 if not df_produtos.empty and 'ID_Produto' in df_produtos.columns and pd.to_numeric(df_produtos['ID_Produto'], errors='coerce').max() > 0 else len(df_produtos) + 1
                
                novo_registro = pd.DataFrame([{
                    "ID_Produto": novo_id,
                    "Nome_Produto": nome,
                    "Categoria": categoria,
                    "Unidade_Medida": unidade,
                    "Custo_Unitario": custo,
                    "Preco_Venda": preco,
                    "Quantidade_Estoque": float(qtd_inicial),
                    "Estoque_Minimo": 0.0
                }])
                df_atualizado = pd.concat([df_produtos, novo_registro], ignore_index=True)
                atualizar_aba("Produtos_Estoque", df_atualizado)
                
                df_entradas = ler_aba("Historico_Entradas")
                nova_entrada = pd.DataFrame([{
                    "ID_Entrada": len(df_entradas) + 1,
                    "Data": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ID_Produto": novo_id,
                    "Quantidade_Adicionada": float(qtd_inicial),
                    "Custo_Unitario": custo
                }])
                atualizar_aba("Historico_Entradas", pd.concat([df_entradas, nova_entrada], ignore_index=True))
                
                st.success(f"✅ Produto '{nome}' cadastrado com sucesso com {qtd_inicial} {unidade}!")
                st.balloons()

    elif opcao == "Adicionar Unidades / Peso a Produto Existente":
        if df_produtos.empty:
            st.info("Nenhum produto cadastrado ainda.")
        else:
            if 'Unidade_Medida' not in df_produtos.columns:
                df_produtos['Unidade_Medida'] = 'UN'
                
            produto_sel = st.selectbox("Selecione o Produto", df_produtos['Nome_Produto'].tolist())
            item_sel = df_produtos[df_produtos['Nome_Produto'] == produto_sel].iloc[0]
            unidade = str(item_sel['Unidade_Medida']).upper()
            
            if unidade in ["KG", "L"]:
                qtd_add = st.number_input(f"Quantidade a Adicionar ({unidade})", min_value=0.001, step=0.100, format="%.3f")
            else:
                qtd_add = st.number_input(f"Quantidade a Adicionar ({unidade})", min_value=1.0, step=1.0, format="%.0f")
            
            if st.button("Adicionar ao Estoque", type="primary"):
                df_produtos['Quantidade_Estoque'] = pd.to_numeric(df_produtos['Quantidade_Estoque'], errors='coerce').fillna(0.0)
                df_produtos.loc[df_produtos['Nome_Produto'] == produto_sel, 'Quantidade_Estoque'] += float(qtd_add)
                atualizar_aba("Produtos_Estoque", df_produtos)
                
                df_entradas = ler_aba("Historico_Entradas")
                nova_entrada = pd.DataFrame([{
                    "ID_Entrada": len(df_entradas) + 1,
                    "Data": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ID_Produto": item_sel['ID_Produto'],
                    "Quantidade_Adicionada": float(qtd_add),
                    "Custo_Unitario": item_sel['Custo_Unitario']
                }])
                atualizar_aba("Historico_Entradas", pd.concat([df_entradas, nova_entrada], ignore_index=True))
                
                st.success(f"✅ Adicionadas {qtd_add} {unidade} ao estoque de '{produto_sel}'.")
                st.balloons()

# -------------------------------------------------------------------
# 3. POSIÇÃO DE ESTOQUE E ALERTAS
# -------------------------------------------------------------------
elif menu == "Posição de Estoque":
    st.header("📊 Posição Geral do Estoque e Alertas")
    
    df_produtos = ler_aba("Produtos_Estoque")
    df_vendas = ler_aba("Vendas")
    
    if not df_produtos.empty:
        df_produtos['Quantidade_Estoque'] = pd.to_numeric(df_produtos['Quantidade_Estoque'], errors='coerce').fillna(0.0)
        df_produtos['Estoque_Minimo'] = pd.to_numeric(df_produtos.get('Estoque_Minimo', 0), errors='coerce').fillna(0.0)
        if 'Unidade_Medida' not in df_produtos.columns:
            df_produtos['Unidade_Medida'] = 'UN'

        col_par1, col_par2 = st.columns(2)
        with col_par1:
            pct_giro = st.slider("Alerta de Estoque Baixo (% do Giro Mensal)", min_value=10, max_value=100, value=50, step=5)
        with col_par2:
            dias_sem_giro = st.number_input("Dias sem Venda para Considerar 'Sem Saída'", min_value=7, max_value=180, value=30, step=1)

        df_vendas_30d = pd.DataFrame()
        if not df_vendas.empty:
            df_vendas['Data_Hora_dt'] = pd.to_datetime(df_vendas['Data_Hora'], errors='coerce')
            data_limite = datetime.now() - timedelta(days=30)
            df_vendas_30d = df_vendas[df_vendas['Data_Hora_dt'] >= data_limite]
        
        giro_mensal = {}
        if not df_vendas_30d.empty:
            df_vendas_30d['Quantidade'] = pd.to_numeric(df_vendas_30d['Quantidade'], errors='coerce').fillna(0.0)
            giro_mensal = df_vendas_30d.groupby('ID_Produto')['Quantidade'].sum().to_dict()

        produtos_baixo = []
        for _, prod in df_produtos.iterrows():
            p_id = prod['ID_Produto']
            est_atual = float(prod['Quantidade_Estoque'])
            est_min = float(prod['Estoque_Minimo'])
            unidade = str(prod['Unidade_Medida']).upper()
            
            giro_prod = giro_mensal.get(p_id, 0.0)
            
            if est_min > 0:
                limite_alerta = est_min
            elif giro_prod > 0:
                limite_alerta = giro_prod * (pct_giro / 100.0)
            else:
                limite_alerta = 1.0 if unidade in ['KG', 'L'] else 10.0
            
            if est_atual <= limite_alerta:
                produtos_baixo.append({
                    "Nome_Produto": prod['Nome_Produto'],
                    "Estoque_Atual": est_atual,
                    "Giro_30d": giro_prod,
                    "Limite_Alerta": limite_alerta,
                    "Unidade": unidade
                })
        
        produtos_sem_saida = []
        data_limite_sem_saida = datetime.now() - timedelta(days=dias_sem_giro)
        
        for _, prod in df_produtos.iterrows():
            p_id = prod['ID_Produto']
            est_atual = float(prod['Quantidade_Estoque'])
            
            if est_atual > 0:
                vendas_prod = pd.DataFrame()
                if not df_vendas.empty:
                    vendas_prod = df_vendas[df_vendas['ID_Produto'] == p_id]
                
                if vendas_prod.empty:
                    produtos_sem_saida.append({
                        "Nome_Produto": prod['Nome_Produto'],
                        "Estoque_Parado": est_atual,
                        "Unidade": prod['Unidade_Medida'],
                        "Ultima_Venda": "Nunca Vendido"
                    })
                else:
                    vendas_prod['Data_Hora_dt'] = pd.to_datetime(vendas_prod['Data_Hora'], errors='coerce')
                    ultima_venda_dt = vendas_prod['Data_Hora_dt'].max()
                    if pd.notnull(ultima_venda_dt) and ultima_venda_dt < data_limite_sem_saida:
                        produtos_sem_saida.append({
                            "Nome_Produto": prod['Nome_Produto'],
                            "Estoque_Parado": est_atual,
                            "Unidade": prod['Unidade_Medida'],
                            "Ultima_Venda": ultima_venda_dt.strftime("%d/%m/%Y")
                        })

        if produtos_baixo:
            st.warning("⚠️ **Alerta de Estoque Baixo / Reposição necessária:**")
            st.dataframe(pd.DataFrame(produtos_baixo), use_container_width=True)
            
        if produtos_sem_saida:
            st.error(f"🛑 **Alerta de Mercadorias Sem Saída (Sem vendas há {dias_sem_giro}+ dias):**")
            st.dataframe(pd.DataFrame(produtos_sem_saida), use_container_width=True)

        st.subheader("Todos os Produtos no Estoque")
        st.dataframe(df_produtos, use_container_width=True)
    else:
        st.info("Nenhum dado encontrado no estoque.")

# -------------------------------------------------------------------
# 4. GERENCIAR / EDITAR OU EXCLUIR PRODUTOS
# -------------------------------------------------------------------
elif menu == "Gerenciar Produtos":
    st.header("🛠️ Gerenciar / Corrigir Produtos Cadastrados")
    
    df_produtos = ler_aba("Produtos_Estoque")
    
    if df_produtos.empty:
        st.info("Nenhum produto cadastrado para gerenciar.")
    else:
        prod_edicao = st.selectbox("Selecione o Produto para Editar ou Excluir", df_produtos['Nome_Produto'].tolist())
        
        if prod_edicao:
            item_atual = df_produtos[df_produtos['Nome_Produto'] == prod_edicao].iloc[0]
            
            with st.form("form_edicao"):
                novo_nome = st.text_input("Nome do Produto", value=str(item_atual['Nome_Produto']))
                nova_cat = st.text_input("Categoria", value=str(item_atual['Categoria']))
                novo_custo = st.number_input("Custo Unitário (R$)", min_value=0.0, value=float(item_atual['Custo_Unitario']), format="%.2f")
                novo_preco = st.number_input("Preço de Venda (R$)", min_value=0.0, value=float(item_atual['Preco_Venda']), format="%.2f")
                novo_est = st.number_input("Quantidade em Estoque", min_value=0.0, value=float(item_atual['Quantidade_Estoque']), format="%.3f")
                
                col_btn1, col_btn2 = st.columns(2)
                salvar_alt = col_btn1.form_submit_button("Salvar Alterações")
                excluir_prod = col_btn2.form_submit_button("Excluir Produto")
                
                if salvar_alt:
                    df_produtos.loc[df_produtos['Nome_Produto'] == prod_edicao, 'Nome_Produto'] = novo_nome
                    df_produtos.loc[df_produtos['Nome_Produto'] == prod_edicao, 'Categoria'] = nova_cat
                    df_produtos.loc[df_produtos['Nome_Produto'] == prod_edicao, 'Custo_Unitario'] = novo_custo
                    df_produtos.loc[df_produtos['Nome_Produto'] == prod_edicao, 'Preco_Venda'] = novo_preco
                    df_produtos.loc[df_produtos['Nome_Produto'] == prod_edicao, 'Quantidade_Estoque'] = novo_est
                    
                    atualizar_aba("Produtos_Estoque", df_produtos)
                    st.success("Alterações salvas com sucesso!")
                    st.balloons()
                    
                if excluir_prod:
                    df_produtos = df_produtos[df_produtos['Nome_Produto'] != prod_edicao]
                    atualizar_aba("Produtos_Estoque", df_produtos)
                    st.success(f"Produto '{prod_edicao}' excluído com sucesso!")
                    st.rerun()

# -------------------------------------------------------------------
# 5. DESPESAS EXTRAS
# -------------------------------------------------------------------
elif menu == "Despesas Extras":
    st.header("💸 Lançamento de Custos e Despesas Extras")
    
    with st.form("form_despesas"):
        data_despesa = st.date_input("Data da Despesa")
        categoria = st.selectbox("Categoria", ["Equipamentos (Freezer, Balcão, etc.)", "Energia Elétrica", "Aluguel", "Manutenção", "Outros"])
        descricao = st.text_input("Descrição (ex: Compra de Freezer para refrigerados)")
        valor = st.number_input("Valor (R$)", min_value=0.0, format="%.2f")
        
        if st.form_submit_button("Registrar Despesa"):
            if valor <= 0:
                st.error("Informe um valor maior que zero.")
            else:
                df_despesas = ler_aba("Despesas_Extras")
                nova_despesa = pd.DataFrame([{
                    "ID_Despesa": len(df_despesas) + 1,
                    "Data": str(data_despesa),
                    "Categoria_Despesa": categoria,
                    "Descricao": descricao,
                    "Valor": valor
                }])
                df_despesas_atualizado = pd.concat([df_despesas, nova_despesa], ignore_index=True)
                atualizar_aba("Despesas_Extras", df_despesas_atualizado)
                st.success("Despesa salva com sucesso!")
                st.balloons()

# -------------------------------------------------------------------
# 6. FATURAMENTO, FINANCEIRO E AUDITORIA DE CANCELAMENTOS
# -------------------------------------------------------------------
elif menu == "Faturamento e Financeiro":
    st.header("📈 Visão Financeira Geral (DRE) & Auditoria")
    
    df_vendas = ler_aba("Vendas")
    df_despesas = ler_aba("Despesas_Extras")
    df_produtos = ler_aba("Produtos_Estoque")
    df_canceladas = ler_aba("Vendas_Canceladas")
    
    faturamento_total = 0.0
    despesas_totais = 0.0
    cmv_total = 0.0
    valor_estoque_custo = 0.0
    valor_estoque_venda = 0.0
    
    if not df_vendas.empty:
        df_vendas['Valor_Total'] = pd.to_numeric(df_vendas['Valor_Total'], errors='coerce').fillna(0.0)
        df_vendas['Quantidade'] = pd.to_numeric(df_vendas['Quantidade'], errors='coerce').fillna(0.0)
        
        if 'Tipo_Saida' in df_vendas.columns:
            vendas_reais = df_vendas[df_vendas['Tipo_Saida'].str.contains("Venda Normal", na=False)]
            faturamento_total = vendas_reais['Valor_Total'].sum()
        else:
            faturamento_total = df_vendas['Valor_Total'].sum()
        
    if not df_despesas.empty:
        df_despesas['Valor'] = pd.to_numeric(df_despesas['Valor'], errors='coerce').fillna(0.0)
        despesas_totais = df_despesas['Valor'].sum()
        
    if not df_vendas.empty and not df_produtos.empty:
        df_produtos['Custo_Unitario'] = pd.to_numeric(df_produtos['Custo_Unitario'], errors='coerce').fillna(0.0)
        vendas_para_cmv = df_vendas[df_vendas['Tipo_Saida'].str.contains("Venda Normal", na=False)] if 'Tipo_Saida' in df_vendas.columns else df_vendas
        df_merged = vendas_para_cmv.merge(df_produtos[['ID_Produto', 'Custo_Unitario']], on='ID_Produto', how='left')
        cmv_total = (df_merged['Quantidade'] * df_merged['Custo_Unitario']).sum()
        
    if not df_produtos.empty:
        df_produtos['Quantidade_Estoque'] = pd.to_numeric(df_produtos['Quantidade_Estoque'], errors='coerce').fillna(0.0)
        df_produtos['Custo_Unitario'] = pd.to_numeric(df_produtos['Custo_Unitario'], errors='coerce').fillna(0.0)
        df_produtos['Preco_Venda'] = pd.to_numeric(df_produtos['Preco_Venda'], errors='coerce').fillna(0.0)
        
        valor_estoque_custo = (df_produtos['Quantidade_Estoque'] * df_produtos['Custo_Unitario']).sum()
        valor_estoque_venda = (df_produtos['Quantidade_Estoque'] * df_produtos['Preco_Venda']).sum()
        
    lucro_bruto = faturamento_total - cmv_total
    lucro_liquido = lucro_bruto - despesas_totais
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Faturamento Bruto Acumulado", f"R$ {faturamento_total:.2f}")
    c2.metric("CMV (Custo Mercadoria Vendida)", f"R$ {cmv_total:.2f}")
    c3.metric("Despesas / Consumo Próprio", f"R$ {despesas_totais:.2f}")
    c4.metric("Lucro Líquido Operacional", f"R$ {lucro_liquido:.2f}")
    
    st.divider()
    
    st.subheader("📦 Capital Imobilizado em Estoque")
    e1, e2, e3 = st.columns(3)
    e1.metric("Total Estoque (a Custo de Compra)", f"R$ {valor_estoque_custo:.2f}")
    e2.metric("Total Estoque (a Preço de Venda)", f"R$ {valor_estoque_venda:.2f}")
    e3.metric("Margem Potencial em Estoque", f"R$ {(valor_estoque_venda - valor_estoque_custo):.2f}")
    
    st.divider()
    
    col_vendas, col_despesas = st.columns(2)
    with col_vendas:
        st.subheader("Histórico Geral de Saídas Ativas")
        st.dataframe(df_vendas, use_container_width=True)
        
    with col_despesas:
        st.subheader("Histórico Geral de Despesas Extras / Custos Internos")
        st.dataframe(df_despesas, use_container_width=True)
        
    # --- CANCELAMENTO COM REGISTRO DE AUDITORIA ---
    st.divider()
    st.subheader("🚫 Cancelamento de Venda com Registro de Auditoria")
    st.markdown("Cancele vendas com erro de lançamento. O sistema estornará o estoque, corrigirá o caixa e **salvará o histórico do cancelamento para auditoria**.")
    
    if df_vendas.empty:
        st.info("Não há vendas registradas para cancelar.")
    else:
        df_vendas['Label_Cancel'] = df_vendas.apply(
            lambda row: f"ID Venda: {row['ID_Venda']} | Data: {row['Data_Hora']} | Produto: {row['Nome_Produto']} | Qtd: {row['Quantidade']} | Total: R$ {float(row['Valor_Total']):.2f}", 
            axis=1
        )
        
        venda_para_cancelar = st.selectbox("Selecione a Venda a Cancelar", df_vendas['Label_Cancel'].tolist())
        motivo_cancelamento = st.text_input("Motivo do Cancelamento (ex: Erro de lançamento / Duplo clique)")
        
        if st.button("⚠️ Confirmar e Auditoriar Cancelamento", type="secondary"):
            if not motivo_cancelamento.strip():
                st.error("⚠️ Por favor, escreva o motivo do cancelamento antes de continuar.")
            else:
                venda_sel = df_vendas[df_vendas['Label_Cancel'] == venda_para_cancelar].iloc[0]
                
                id_venda_alvo = venda_sel['ID_Venda']
                id_produto_alvo = venda_sel['ID_Produto']
                qtd_estornar = float(venda_sel['Quantidade'])
                
                # 1. Copia o registro para a aba 'Vendas_Canceladas' para auditoria
                registro_cancelado = pd.DataFrame([{
                    "ID_Venda_Original": id_venda_alvo,
                    "Data_Hora_Venda": venda_sel['Data_Hora'],
                    "Data_Hora_Cancelamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ID_Produto": id_produto_alvo,
                    "Nome_Produto": venda_sel['Nome_Produto'],
                    "Quantidade_Estornada": qtd_estornar,
                    "Valor_Total": venda_sel['Valor_Total'],
                    "Motivo": motivo_cancelamento
                }])
                
                df_canceladas_novo = pd.concat([df_canceladas, registro_cancelado], ignore_index=True)
                atualizar_aba("Vendas_Canceladas", df_canceladas_novo)
                
                # 2. Devolve o produto ao estoque
                df_produtos['ID_Produto'] = pd.to_numeric(df_produtos['ID_Produto'], errors='coerce')
                df_produtos['Quantidade_Estoque'] = pd.to_numeric(df_produtos['Quantidade_Estoque'], errors='coerce').fillna(0.0)
                
                mask_prod = df_produtos['ID_Produto'] == id_produto_alvo
                if mask_prod.any():
                    df_produtos.loc[mask_prod, 'Quantidade_Estoque'] += qtd_estornar
                    atualizar_aba("Produtos_Estoque", df_produtos)
                
                # 3. Remove da tabela de vendas ativas
                df_vendas_novo = df_vendas[df_vendas['ID_Venda'] != id_venda_alvo]
                if 'Label_Cancel' in df_vendas_novo.columns:
                    df_vendas_novo = df_vendas_novo.drop(columns=['Label_Cancel'])
                    
                atualizar_aba("Vendas", df_vendas_novo)
                
                st.success(f"✅ Venda ID {id_venda_alvo} cancelada e movida para a aba de Auditoria! {qtd_estornar} unidade(s) devolvida(s) ao estoque.")
                st.balloons()
                st.rerun()

    # Exibe a tabela de auditoria de cancelamentos
    if not df_canceladas.empty:
        st.subheader("🕵️ Histórico de Vendas Canceladas (Auditoria)")
        st.dataframe(df_canceladas, use_container_width=True)

# -------------------------------------------------------------------
# 7. FECHAMENTO DIÁRIO & CURVA ABC
# -------------------------------------------------------------------
elif menu == "Fechamento Diário & Curva ABC":
    st.header("📆 Fechamento Diário de Caixa & Curva ABC de Vendas")
    
    df_vendas = ler_aba("Vendas")
    df_despesas = ler_aba("Despesas_Extras")
    
    tab_caixa, tab_abc = st.tabs(["💵 Fechamento do Dia", "📊 Curva ABC (Ranking)"])
    
    with tab_caixa:
        st.subheader("🔍 Conferência Diária de Caixa")
        
        data_sel = st.date_input("Selecione a Data para Conferência", value=datetime.now())
        data_str = data_sel.strftime("%Y-%m-%d")
        
        vendas_dia = pd.DataFrame()
        faturamento_dia = 0.0
        qtd_vendas_dia = 0
        
        if not df_vendas.empty:
            df_vendas['Data_Sem_Hora'] = pd.to_datetime(df_vendas['Data_Hora'], errors='coerce').dt.strftime("%Y-%m-%d")
            vendas_dia = df_vendas[df_vendas['Data_Sem_Hora'] == data_str]
            
            if not vendas_dia.empty:
                vendas_dia['Valor_Total'] = pd.to_numeric(vendas_dia['Valor_Total'], errors='coerce').fillna(0.0)
                vendas_normais = vendas_dia[vendas_dia['Tipo_Saida'].str.contains("Venda Normal", na=False)] if 'Tipo_Saida' in vendas_dia.columns else vendas_dia
                faturamento_dia = vendas_normais['Valor_Total'].sum()
                qtd_vendas_dia = len(vendas_normais)
        
        despesas_dia = pd.DataFrame()
        total_despesas_dia = 0.0
        
        if not df_despesas.empty:
            df_despesas['Data_Limpa'] = pd.to_datetime(df_despesas['Data'], errors='coerce').dt.strftime("%Y-%m-%d")
            despesas_dia = df_despesas[df_despesas['Data_Limpa'] == data_str]
            
            if not despesas_dia.empty:
                despesas_dia['Valor'] = pd.to_numeric(despesas_dia['Valor'], errors='coerce').fillna(0.0)
                total_despesas_dia = despesas_dia['Valor'].sum()
        
        saldo_caixa_dia = faturamento_dia - total_despesas_dia
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"Faturamento em {data_sel.strftime('%d/%m/%Y')}", f"R$ {faturamento_dia:.2f}")
        m2.metric("Total de Transações (Vendas)", f"{qtd_vendas_dia}")
        m3.metric("Despesas / Custos do Dia", f"R$ {total_despesas_dia:.2f}")
        m4.metric("Saldo do Caixa no Dia", f"R$ {saldo_caixa_dia:.2f}")
        
        st.divider()
        
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.write(f"**Vendas Realizadas em {data_sel.strftime('%d/%m/%Y')}:**")
            if not vendas_dia.empty:
                st.dataframe(vendas_dia[['Data_Hora', 'Nome_Produto', 'Quantidade', 'Valor_Total', 'Tipo_Saida']], use_container_width=True)
            else:
                st.info("Nenhuma venda registrada nesta data.")
                
        with col_d2:
            st.write(f"**Despesas / Ocorrências em {data_sel.strftime('%d/%m/%Y')}:**")
            if not despesas_dia.empty:
                st.dataframe(despesas_dia[['Data', 'Categoria_Despesa', 'Descricao', 'Valor']], use_container_width=True)
            else:
                st.info("Nenhuma despesa registrada nesta data.")

    with tab_abc:
        st.subheader("🏆 Ranking de Vendas e Curva ABC de Produtos")
        
        if not df_vendas.empty:
            vendas_validas = df_vendas[df_vendas['Tipo_Saida'].str.contains("Venda Normal", na=False)] if 'Tipo_Saida' in df_vendas.columns else df_vendas
            
            if not vendas_validas.empty:
                vendas_validas['Valor_Total'] = pd.to_numeric(vendas_validas['Valor_Total'], errors='coerce').fillna(0.0)
                vendas_validas['Quantidade'] = pd.to_numeric(vendas_validas['Quantidade'], errors='coerce').fillna(0.0)
                
                ranking = vendas_validas.groupby('Nome_Produto').agg(
                    Total_Faturado=('Valor_Total', 'sum'),
                    Quantidade_Vendida=('Quantidade', 'sum')
                ).reset_index()
                
                ranking = ranking.sort_values(by='Total_Faturado', ascending=False)
                
                total_geral = ranking['Total_Faturado'].sum()
                if total_geral > 0:
                    ranking['% do Faturamento'] = (ranking['Total_Faturado'] / total_geral) * 100
                    ranking['% Acumulada'] = ranking['% do Faturamento'].cumsum()
                    
                    def classificar_abc(row):
                        if row['% Acumulada'] <= 70:
                            return 'Classe A (Mais Importante)'
                        elif row['% Acumulada'] <= 90:
                            return 'Classe B (Intermediário)'
                        else:
                            return 'Classe C (Menor Giro)'
                            
                    ranking['Classe ABC'] = ranking.apply(classificar_abc, axis=1)
                    
                    ranking['Total_Faturado'] = ranking['Total_Faturado'].apply(lambda x: f"R$ {x:.2f}")
                    ranking['% do Faturamento'] = ranking['% do Faturamento'].apply(lambda x: f"{x:.2f}%")
                    ranking['% Acumulada'] = ranking['% Acumulada'].apply(lambda x: f"{x:.2f}%")
                    
                    st.dataframe(ranking, use_container_width=True)
                else:
                    st.info("Nenhuma venda faturada encontrada para gerar a curva ABC.")
            else:
                st.info("Nenhuma venda normal registrada ainda.")
        else:
            st.info("Sem dados de vendas disponíveis para análise.")
