# Avaliação técnica para integrar Manuseg3d e Cryo3D Editor

Data: 21/09/2026. Escopo: análise de código, testes existentes, empacotamento e documentação oficial de interoperabilidade. Este documento propõe a integração; não implementa a fusão.

## Parecer

A integração é viável e tem bastante código reaproveitável. A base recomendada é o motor de segmentação de manu_seg_3d.py, os recursos de edição/visualização de cryo3d_editor_2.py e a estrutura de distribuição do pacote napari-cryo3d-editor. Antes da interface unificada, é necessário consolidar coordenadas, identidade dos objetos, importação/exportação e persistência.

O nome considerado nesta avaliação é ArtiaX, extensão do ChimeraX. O objetivo de interoperabilidade é ler, visualizar, editar e reexportar listas de partículas com posições e orientações corretas. Abrir uma sessão completa do ChimeraX é outro requisito, não equivalente à leitura das listas.

## Evidência e limites

Foram examinados os arquivos principais, funções de cálculo, leitores, escritores, callbacks, estado, composição de segmentações, testes e manifesto do pacote. As referências de linha correspondem ao snapshot registrado em INTEGRACAO_PLUGINS_SNAPSHOT.json.

A avaliação é estática. Não foi possível executar a suíte científica: o Python disponível pelo comando genérico não tem NumPy; o executável Python empacotado falhou ao iniciar. O terminal PowerShell também apresentou falha ao carregar hostfxr.dll. Nenhum resultado de benchmark ou teste comentado nos arquivos foi tratado como medição realizada nesta avaliação. A interface gráfica e a correspondência com dados reais no ArtiaX ainda precisam ser validadas.

## 1. O que existe em cada projeto

| Componente | Estado observado | Destino recomendado |
|---|---|---|
| manu_seg_3d.py, aproximadamente 6.158 linhas | Segmentação, campos escalares, pincel, malhas, composição e partículas no mesmo módulo | Extrair núcleo científico, serviços e painéis |
| test_plugin.py, aproximadamente 2.592 linhas | 15 grupos de testes, com harness próprio e objetos simulados | Preservar cenários; acrescentar integração real |
| cryo3d_editor.py, aproximadamente 3.182 linhas | Limpeza, cores, renderização e filmes | Comparar mudanças relevantes antes da consolidação |
| cryo3d_editor_2.py, aproximadamente 3.848 linhas | Acrescenta recursos de malhas e estado mais completo de animação | Base funcional preferida do editor, sujeita a regressão |
| pacote _widget.py, aproximadamente 2.846 linhas | Distribuição instalável, implementação divergente dos scripts | Reaproveitar embalagem, substituir a cópia monolítica |
| cryoet_cleaner_v1_10.py e backups v1.9 | Histórico funcional e origem compartilhada | Referência de migração, fora do caminho ativo |

As contagens são descritivas, não métricas de qualidade. Os scripts não foram considerados versões ordenadas apenas pelo nome.

### Manuseg3d

Pontos fortes:

- Contornos abertos e fechados, anotação por fatia e gerenciamento de objetos.
- Curvas abertas reamostradas por comprimento de arco, correspondência entre traços, correção de orientação e interpolação entre fatias.
- Interpolação linear, nearest-neighbor e PCHIP; avisos de lacunas e traços sem correspondência.
- Campo de distância assinado para regiões fechadas e distância negativa para curvas abertas.
- Campos float32 recortados por bounding box, cache e construção em QThread.
- Suavização, espessura e extração de superfícies a partir do campo.
- Pincel guiado por densidade com Otsu/adaptativo e desfazer por regiões.
- Importação de volumes externos, promoção de máscaras para campos e composição com contornos manuais.
- Leitura/escrita de malhas OBJ/PLY/STL e exportação de volumes MRC.
- Leitura inicial de MOTL/EM, NPY, STAR e tabelas de partículas.
- Testes de sinal do campo, interpolação, I/O, workers, desenho, composição e partículas.

Limitações:

- A classe MembraneTab concentra interface, dados, importação, processamento e exportação.
- PluginState armazena somente o viewer; não representa um projeto científico.
- ContourObject serve tanto para contornos quanto para máscaras externas convertidas. Isso dificulta distinguir representação original e derivados.
- O caminho de desenho assume fatias em Z e posições Y/X. Edição multiplanar precisa de um contrato de plano explícito.
- O tomograma de referência é escolhido implicitamente pela primeira Image, sem vínculo persistente.
- A promoção de uma máscara não cria contornos editáveis: o próprio código bloqueia desenho direto sobre o objeto promovido.
- Não encontrei um ciclo completo salvar/abrir projeto. Exportação de debug e volumes não reconstrói todos os objetos, listas, relações e parâmetros.
- Espessuras/distâncias são calculadas em voxels em várias funções; amostragem anisotrópica exige mudança no cálculo, não apenas no rótulo do slider.
- A presença de testes sintéticos não demonstra compatibilidade visual ou geométrica com ArtiaX.

### Cryo3D Editor

Pontos fortes:

- Limpeza de componentes, erosão, remoção por máscara, cores e fusão de labels.
- Prévia, progresso, cancelamento em algumas operações e GPU opcional.
- Renderização, contraste, presets e snapshots.
- Animação por keyframes e giro 360°.
- A variante _2 lê superfícies e permite selecionar/apagar faces.
- Keyframes da variante _2 incluem visibilidade, opacidade, contraste, modo de renderização e cores de labels.
- Há pacote com pyproject.toml e manifesto npe2.

Limitações:

- Estado vinculado a nomes de camada, sujeito a renomeação, remoção e recriação.
- Escala global isotrópica em voxel_nm, insuficiente para várias aquisições/resoluções.
- Limpeza e análise agrupam primeiro o foreground binário; objetos encostados com IDs diferentes podem ser tratados juntos.
- O preenchimento de buracos atribui 1 aos novos voxels, sem determinar a instância proprietária.
- Undo de volumes guarda até dez cópias completas; malhas têm histórico separado.
- Cortes de malha alteram a Surface, sem atualização automática da segmentação que possa tê-la originado.
- Há acessos a APIs privadas do viewer/VisPy e tratamentos amplos de exceção.
- Não identifiquei suíte equivalente à do Manuseg3d no pacote inspecionado.
- A dependência napari>=0.4.18, sem uma matriz validada, não demonstra compatibilidade com todas as versões posteriores.

## 2. Problemas prioritários demonstráveis no código

P0 indica risco de integridade geométrica ou dos dados. P1 indica lacuna relevante para uso integrado.

| Prioridade | Evidência | Consequência | Tratamento |
|---|---|---|---|
| P0 | manual:4131–4172 usa ndi.zoom pela razão entre shapes | Um recorte pode ser esticado como se fosse binning | Alinhar por metadados e transformação física; não inferir registro só pelo shape |
| P0 | manual:4105–4108, 4905–4912, 5491–5494 e 6055–6056 criam camadas sem a transformação da referência | Contornos, labels e superfícies podem não coincidir com imagem calibrada | Serviço único de geometria |
| P0 | editor2:819 usa voxel_nm × 10; package:475 usa voxel_nm | Scripts e pacote têm convenções de escala distintas | Unidade mundial explícita em todas as camadas |
| P0 | manual:4323–4326 transforma todos os IDs não zero em máscara e recalcula componentes | Instâncias encostadas e classes perdem identidade | Preservar IDs/classes; componentes apenas como operação explícita |
| P0 | manual:4106 e editor2:1577 convertem qualquer volume para inteiro | Probabilidades/escores são truncados | Distinguir imagem contínua, máscara, classe e instância |
| P0 | manual:1649–1652 não escreve voxel_size/origin; editor2:2971 converte labels para int16 | Perda de calibração no primeiro; overflow no segundo para IDs acima de 32767 | Escritor comum com validação de dtype e metadados |
| P0 | manual:1853–1969 | STAR centrado não suportado; shifts STAR não aplicados; nomes textuais viram NaN | Adaptadores explícitos e preservação da tabela original |
| P0 | manual:5944–6018 | Numeração por posição do contorno, mas base externa por quantidade ativa | Alocador único de IDs |
| P1 | manual:4432 usa chave external/nome/shape e campo é snapshot | Edição posterior da camada pode deixar campo antigo | Revisões e invalidação de derivados |
| P1 | editor2:855–862 copia o volume a cada ação | Memória cresce rapidamente | Histórico por regiões/chunks com orçamento |
| P1 | editor2:1973–2006 modifica só a superfície | Malha e labels divergem após apagar faces | Representações vinculadas com operação explícita |
| P1 | manual:5989 usa sm - offset_c para Image | Espessura diverge do caminho Labels | Contrato matemático comum e teste de regressão |

Exemplo da colisão de IDs: com primeiro contorno vazio e segundo contorno ativo, o manual escreve label 2. Como n_active é 1, o primeiro componente externo também recebe 2. Os objetos ficam indistinguíveis apesar de ocuparem regiões separadas. A seleção de dtype pela quantidade ativa também não cobre necessariamente o maior label atribuído.

Exemplo do sinal: Labels usa field >= -offset, equivalente a field + offset >= 0. O caminho Image usa field - offset antes de limitar o fundo a zero. Isso desloca o limiar no sentido oposto; em campos abertos negativos, pode apagar a contribuição. É uma inconsistência algébrica observada estaticamente, ainda sem teste executado nesta sessão.

Outro cuidado: suavização e granulação podem modificar a geometria exportada. O plugin já sinaliza parte dessa distinção. No produto integrado, segmentação usada em medidas e representação ilustrativa precisam ter derivação explícita e exportações identificáveis.

## 3. Arquitetura do plugin único

Recomendação: manter um pacote instalável e uma interface principal, com módulos internos independentes.

    napari_cryo3d_editor/
        model/          projeto, tomogramas, objetos, revisões
        geometry/       unidades, eixos, transformações, amostragem
        io/             volumes, malhas, listas, projeto
        segmentation/   contornos, interpolação, pincel, composição
        processing/     limpeza, métricas, operações por instância
        particles/      normalização, filtros, orientação, exportação
        rendering/      superfícies, glyphs, mapas de referência
        animation/      keyframes, snapshots, vídeo
        services/       jobs, histórico, cache, vínculos com camadas
        ui/             painéis e controles
        tests/

As camadas napari são vistas dos dados. O projeto mantém IDs estáveis próprios, independentes do nome exibido.

| Entidade | Dados mínimos |
|---|---|
| Project | versão de esquema, tomogramas, objetos, operações e cena |
| Tomogram | ID, origem, dimensões, espaçamento XYZ, unidade, orientação e transformação |
| Segmentation | tipo semântico, IDs/classes, volume, fonte, versão e tomograma |
| ContourSet | plano, curvas, fatias, parâmetros e objeto de destino |
| Surface | vértices/faces, unidade, transformação, fonte e revisão |
| ParticleSet | IDs, tomograma, posições, shifts, rotações, scores/classes, colunas originais |
| Operation | entradas, parâmetros, saída, revisões, efeito no undo |
| Scene | cores, visibilidade, câmera, keyframes e parâmetros de renderização |

Um tomograma é referência explícita por conjunto de dados; o projeto pode conter vários. Nomes são editáveis sem mudar identidade. A relação mask → surface não significa que toda edição de superfície possa ser invertida automaticamente.

O manifesto npe2 deve registrar widgets, leitores e escritores; hoje o manifesto local registra somente o widget. A documentação oficial admite essas contribuições no pacote. [Manifesto napari](https://napari.org/stable/plugins/technical_references/manifest.html)

### Geometria

Sugestão: arrays em ZYX, mundo físico em Å e controles científicos podendo mostrar nm. O adaptador de cada formato documenta XYZ/ZYX, base 0/1, binning, unidade e referência da origem.

A transformação conceitual deve ser:

    índice de origem → posição física → transformação de registro → índice no tomograma de referência

Não aplicar escala duas vezes: geometria já em Å não recebe novamente Å/voxel. Recortes precisam de translação; flips precisam de deslocamento associado; dimensões iguais não demonstram alinhamento.

Registrar espaçamento por eixo, origem, ordem dos eixos MRC e interpretação dos campos de início/origem. Em TIFF, tratar unidade e metadados por eixo. Em NPY/CSV sem metadados, apresentar parâmetros explícitos e lembrar a escolha no projeto.

Preservar a transformação composta, não apenas scale/translate; napari também oferece rotate, shear e affine. [Camadas e transformações](https://napari.org/dev/api/napari.layers.Layer.html)

Na conversão para uma grade comum, labels usam vizinho mais próximo; dados contínuos usam interpolação adequada ao significado. O simples overlay pode manter grades originais para evitar cópia e reamostragem desnecessárias.

## 4. Segmentação manual e deep learning no mesmo fluxo

O fluxo proposto é carregar tomograma, importar previsão, escolher seu significado, conferir alinhamento, corrigir objetos e exportar resultado rastreável.

Quatro tipos precisam ser distintos:

1. Máscara binária: foreground/background.
2. Labels semânticos: classes biológicas.
3. Labels de instância: identidade de cada objeto.
4. Scoremap/probabilidade: campo contínuo, com semântica de limiar declarada.

Não assumir que toda imagem float é probabilidade entre zero e um. MemBrain-seg documenta scoremaps e limiar padrão zero, além de saída MRC e opção de componentes conectados. Deve haver um perfil de importação para distinguir esses resultados e preservar escala. [MemBrain-seg](https://github.com/teamtomo/membrain-seg/blob/main/docs/Usage/Segmentation.md)

TARDIS tem saídas semânticas e instâncias, incluindo volumes, CSV [ID,X,Y,Z], grafos e malhas. Um CSV de instâncias de membranas precisa de um leitor próprio: seus pontos descrevem a estrutura segmentada, não necessariamente partículas. O leitor genérico atual, sem cabeçalho, interpreta as quatro primeiras colunas como x,y,z,score — portanto leria esse CSV errado. [TARDIS 3D](https://smlc-nysbc.github.io/TARDIS/usage/3d_membrane.html)

Operações de correção:

- Adicionar região a uma instância existente ou criar uma nova.
- Apagar região, sem que uma recomposição posterior restaure o foreground da previsão.
- Substituir previsão dentro de ROI.
- Unir/dividir instâncias com remapeamento registrado.
- Bloquear regiões revisadas.
- Mostrar sobreposições e escolher precedência.
- Recuperar previsão original e comparar versões.

Representar adições e exclusões explicitamente. A composição atual prioriza o foreground manual, mas uma região manual com valor zero não expressa remoção da segmentação automática.

Preservar tabelas de mapeamento: arquivo de origem + ID original → ID estável no projeto → ID na exportação. O modo binário deve ser opção explícita.

Executar MemBrain/TARDIS dentro da interface pode ser uma etapa posterior via processo/ambiente separado, com logs, cancelamento, checkpoint e parâmetros registrados. A importação robusta de resultados existentes vem primeiro; não exigir PyTorch/CUDA apenas para abrir ou editar dados.

## 5. Partículas e ArtiaX

ArtiaX modela partículas com posições, orientações, shifts e metadados; também representa mapas de referência nas posições das partículas. Isso é mais amplo que marcadores. [Artigo do ArtiaX](https://pmc.ncbi.nlm.nih.gov/articles/PMC9667824/)

### Situação atual

| Formato | Suporte observado | Trabalho necessário |
|---|---|---|
| TOM/EM MOTL .em | Leitor, posições mais shifts, conversão de base e ângulos preservados | Manter todas as colunas; validar variantes e endian; escrever de volta |
| MOTL .npy | Arrays de 20 colunas | Metadados e esquema explícitos; não confundir com volume NPY |
| STAR com rlnCoordinateXYZ | Posições e alguns ângulos/scores | Shifts, nomes, optics, múltiplos tomogramas e round-trip |
| STAR centrado RELION 5 | Recusa explícita | Dimensões, Å/voxel, centro e orientações completas |
| STOPGAP STAR | Aliases de posição/ângulo | Shifts e metadados completos |
| CSV/TSV/XYZ | Leitura genérica | Esquema, unidade, base, coluna de ID e validação |
| Dynamo .tbl | Sem leitor dedicado | Adaptador próprio |
| PEET/IMOD | Sem leitor dedicado | Tratar arquivos de posição/modelo e motive list associados |

A prioridade sugerida, enquanto os formatos reais do laboratório não forem confirmados, é MOTL/EM e STAR, já presentes parcialmente, seguidos de Dynamo e PEET. A árvore atual do ArtiaX mantém adaptadores separados, incluindo RELION e RELION5. [Adaptadores ArtiaX](https://github.com/FrangakisLab/ArtiaX/tree/main/src/io)

O código atual também:

- Mantém uma lista ativa em self._particles; não há gerenciador de coleções equivalente a um projeto.
- Pode mostrar partículas de vários tomogramas sobre a mesma imagem.
- Converte colunas textuais para números/NaN; isso perde rlnTomoName textual.
- Guarda três ângulos mas não aplica rotação a geometria.
- Copia scale/translate da imagem para Points, sem a transformação completa.
- Filtra score por quantil; isso é útil, mas deve coexistir com limiar numérico e seleção por classe.
- Não oferece escritor de partículas que preserve a tabela de origem.

### Contrato de orientação e posição

Manter posição original, shift original, unidades e posição final como campos distintos. Normalizar rotações para matriz 3×3 ou quaternion com convenção documentada; conservar os ângulos originais para exportação.

A transformação da referência para cada partícula deve considerar o centro do mapa, seu espaçamento, rotação e translação no tomograma. A convenção de rotação ativa/passiva e o sentido do shift pertencem a cada adaptador.

RELION 5 usa coordenadas centradas em Å, diferentes do esquema em pixels anterior. [RELION particle set](https://relion.readthedocs.io/en/latest/Reference/STA/Datatypes/particle_set.html)

O leitor RELION5 do ArtiaX converte coordenadas usando dimensões e tamanho do voxel, trata shifts com sinal específico e combina orientações quando os dois conjuntos de ângulos existem. A integração deve ser validada contra essa referência e arquivos reais, incluindo volumes de dimensões pares/ímpares. [Leitor RELION5 do ArtiaX](https://raw.githubusercontent.com/FrangakisLab/ArtiaX/main/src/io/RELION5/RELION5ParticleData.py)

Para RELION em pixels, ignorar rlnOrigin* também é insuficiente: o leitor do ArtiaX trata os shifts explicitamente. [Leitor RELION do ArtiaX](https://raw.githubusercontent.com/FrangakisLab/ArtiaX/main/src/io/RELION/RELIONParticleData.py)

### Visualização e edição propostas

Três níveis:

1. Points para navegação e muitos objetos.
2. Eixos/setas ou formas assimétricas para conferir orientação.
3. Superfície de uma média/template posicionada e orientada em cada partícula.

O terceiro exige orçamento de geometria, simplificação, visibilidade por ROI e benchmark. Duplicar uma malha pesada para cada partícula não deve ser a implementação padrão. Avaliar renderização com instâncias antes de prometer desempenho em grandes listas.

Gerenciar várias coleções; selecionar por tomograma, classe, score, ROI e distância à membrana. Exportar o subconjunto escolhido com IDs, nomes e colunas preservados. Uma esfera sozinha não valida orientação: usar referência assimétrica nos testes.

Análise combinada futura: distância partícula–membrana, associação a uma instância, orientação versus normal local e distribuição espacial. Todas as medidas usam a geometria científica, em unidades físicas.

## 6. Robustez, armazenamento e memória

Um projeto deve salvar metadados versionados e dados necessários à retomada: contornos, máscaras editadas, partículas originais/normalizadas, efeitos, relações, seleção e keyframes. Proposta: manifesto JSON e arrays em armazenamento segmentado, como Zarr, com caminhos relativos quando possível. A implementação deve fixar a versão do esquema e do backend após teste.

Campos externos promovidos não podem existir apenas como cache descartável: é preciso persistir a máscara fonte ou referência confiável e a receita de reconstrução.

Para volumes grandes:

- Ler por mmap/chunks quando aplicável.
- Trabalhar em ROI com halo adequado para filtros.
- Não executar EDT global como se blocos independentes fossem equivalentes; tratar limites e validar o algoritmo.
- Cache com orçamento em bytes e revisão da fonte.
- Undo por diferenças/ROI e checkpoints.
- Um coordenador de jobs por projeto, com snapshots imutáveis das entradas.
- Descartar resultados cujo objeto mudou ou foi removido.
- Cancelamento cooperativo, limpeza de workers e desconexão de callbacks ao fechar.
- Atualização das camadas somente na thread de GUI.

Exemplo aritmético: 1024³ em uint32 ocupa 4 GiB; dez cópias completas de histórico já somam 40 GiB, sem imagens, temporários ou GPU. Esse cálculo é ilustrativo, não um benchmark do plugin.

MRC deve ter exportação calibrada e dtype validado. Se o formato alvo não representar IDs ou transformação sem perda, oferecer outro formato ou uma reamostragem explícita com metadados auxiliares; não converter silenciosamente.

## 7. Interface proposta

Um painel principal com tomograma de referência e árvore de objetos persistentes. Seções:

| Seção | Função |
|---|---|
| Projeto e dados | Abrir, associar, calibrar, salvar e recuperar |
| Segmentar | Contornos, pincel e importação de previsões |
| Revisar | Apagar, unir/dividir, limpar e comparar |
| Partículas | Listas, filtros, orientação, mapas e exportação |
| Visualizar | Cores, superfícies e renderização |
| Exportar | Dados científicos, intercâmbio, snapshots e filmes |

Segmentação manual e previsão devem operar nos mesmos objetos de trabalho. Cada objeto mostra origem, classe, tomograma e situação de revisão. Operações visuais ficam ligadas ao objeto, mas não alteram a segmentação científica sem uma ação explícita.

## 8. Sequência de integração e aceitação

| Etapa | Entrega | Critério para avançar |
|---|---|---|
| 0. Congelar referência | Snapshot, cenários reais e comparação das variantes | Saber quais comportamentos preservar |
| 1. Coordenadas e I/O | GeometryService, tomograma explícito, leitores/escritores comuns | Pontos, labels e malhas coincidem sob escala, origem e binning |
| 2. Modelo e pacote único | UUIDs, revisões, serviços e widget npe2 | Instalação limpa e nenhuma dependência dos scripts soltos |
| 3. Segmentação integrada | Preservação de instâncias, correções aditivas/subtrativas, efeitos derivados | Correção manual mantém IDs e não ressuscita regiões apagadas |
| 4. Partículas | Adaptadores MOTL/STAR completos, orientação e round-trip | Mesma posição/orientação no napari e ArtiaX |
| 5. Projeto e estabilidade | Persistência, undo, cancelamento e orçamento de memória | Reabrir/reverter operações sem perda |
| 6. Ampliação | Dynamo/PEET, processamento externo e análises espaciais | Fixtures e critérios específicos por formato |

Persistência básica e snapshots de recuperação devem começar junto do modelo na etapa 2; a etapa 5 consolida recuperação e testes de falha. Recursos de vídeo/cores podem ser portados junto dos objetos e validados após estabilizar a geometria. Não é necessário concluir integração de inferência para entregar importação e correção completas.

### Matriz mínima de testes

- Phantom assimétrico com pontos conhecidos: XYZ/ZYX, base 0/1, flips, origem não zero, crop, binning e anisotropia.
- Round-trip de labels com IDs esparsos e limites 255/256, 32767/32768 e 65535/65536; exigir igualdade dos IDs quando o formato permitir.
- Máscara binária, classes, instâncias encostadas e scoremaps negativos/contínuos.
- Contorno vazio antes de contorno ativo, seguido de composição externa.
- Mesmo offset em Labels, superfície e Image; comparar geometria definida, não apenas aparência.
- Adicionar/apagar/substituir e depois regenerar/exportar.
- Editar/renomear/remover fonte após criar um derivado.
- STAR com optics e particles, nomes textuais, múltiplos tomogramas, shifts não zero e coordenadas centradas.
- MOTL com shifts, classes, IDs e ângulos não triviais.
- Referência assimétrica com rotações de 90° e combinações não triviais; comparar matrizes, já que Euler não tem representação única.
- Importar → selecionar → exportar → reabrir no ArtiaX; comparar posição, orientação, contagem, IDs e metadados.
- Fechar painel durante cálculo, cancelar, receber resultado antigo, desfazer e salvar/reabrir.
- Qt/napari real: desenho, layers, renomeação, câmera, mesh picking e exportação de vídeo.
- Benchmarks em volumes e listas representativos do laboratório, registrando CPU/RAM/GPU; definir limites a partir dessas medições.

Tolerâncias geométricas precisam corresponder à precisão do formato e à reamostragem. Para transformações reversíveis em memória, testar erro numérico muito inferior a um voxel; para grades reamostradas, medir separadamente erro de discretização. Não usar apenas “parece alinhado” como aceitação.

## 9. Decisões recomendadas

- Um único pacote modular, baseado nas melhores partes das implementações atuais.
- Um contrato geométrico comum antes de consolidar as abas.
- Identidade e classe preservadas desde a importação.
- MOTL e STAR como primeira entrega de partículas; formatos reais do laboratório determinam a ordem seguinte.
- Importação/exportação de dados como primeira integração com ArtiaX; sessão ChimeraX e controle remoto ficam fora dessa equivalência inicial.
- Projetos recuperáveis, testes de round-trip e ensaios reais como condição de robustez.
- Manter separado o dado usado em medida e a aparência produzida para figuras/filmes.

Resultado esperado: abrir o tomograma, importar MemBrain/TARDIS ou outro produtor, corrigir manualmente as mesmas instâncias, sobrepor partículas orientadas, salvar a sessão de trabalho e exportar dados calibrados para continuar no ArtiaX.
