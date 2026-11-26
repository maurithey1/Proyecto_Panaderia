# Diagramas Entidad-Relación (Mermaid) — Panadería Los Tres Spa

En este documento se respaldan los códigos fuente en formato Mermaid para la generación y actualización de los diagramas Entidad-Relación (MER) del sistema.

---

## 1. MER — Modelo de Dominio del Negocio (Versión Limpia)

Este diagrama representa exclusivamente las 32 entidades operativas y reglas de negocio del software de la panadería, omitiendo las tablas administrativas por defecto de Django.

```mermaid
erDiagram

    %% ====================================================
    %% 1. USUARIOS, PERFILES DE ACCESO Y FIDELIZACIÓN
    %% ====================================================

    core_usuario {
        bigint id PK
        varchar_128 password
        datetime_6 last_login
        tinyint_1 is_superuser
        varchar_150 username
        varchar_150 first_name
        varchar_150 last_name
        varchar_254 email
        tinyint_1 is_staff
        tinyint_1 is_active
        datetime_6 date_joined
        varchar_20 rol
    }

    core_cliente {
        bigint id PK
        varchar_255 direccion
        varchar_20 telefono
        bigint user_id FK
    }

    core_cajero {
        bigint id PK
        int num_caja_asignada
        varchar_50 jornada
        bigint user_id FK
    }

    core_administrador {
        bigint id PK
        varchar_50 nivel_acceso
        bigint user_id FK
    }

    core_puntosfidelizacion {
        bigint id PK
        int puntos_acumulados
        datetime_6 fecha_actualizacion
        bigint cliente_id FK
    }

    core_movimientopuntos {
        bigint id PK
        varchar_20 tipo
        int puntos
        int saldo_resultante
        varchar_255 descripcion
        datetime_6 fecha
        bigint cliente_id FK
        bigint pedido_id FK
    }

    %% ====================================================
    %% 2. CATÁLOGO, PRODUCTOS, TURNOS Y RECETAS
    %% ====================================================

    core_categoria {
        bigint id PK
        varchar_100 nombre
        longtext descripcion
        tinyint_1 es_horno
    }

    core_producto {
        bigint id PK
        varchar_150 nombre
        longtext descripcion
        decimal_10_2 precio
        int stock
        int stock_critico
        varchar_500 imagen_url
        tinyint_1 activo
        bigint categoria_id FK
        varchar_10 unidad_medida
        varchar_100 unidades_por_kg
    }

    core_turno {
        bigint id PK
        varchar_50 nombre
        time_6 hora_inicio
        time_6 hora_fin
        tinyint_1 lunes
        tinyint_1 martes
        tinyint_1 miercoles
        tinyint_1 jueves
        tinyint_1 viernes
        tinyint_1 sabado
        tinyint_1 domingo
        tinyint_1 activo
    }

    core_producto_turnos {
        bigint id PK
        bigint producto_id FK
        bigint turno_id FK
    }

    core_receta {
        bigint id PK
        varchar_150 nombre
        longtext descripcion
        bigint producto_id FK
    }

    core_ingredientereceta {
        bigint id PK
        decimal_10_3 cantidad
        bigint insumo_id FK
        bigint receta_id FK
    }

    %% ====================================================
    %% 3. MATERIAS PRIMAS, ENVASES, PRECIOS Y ABASTECIMIENTO
    %% ====================================================

    core_insumo {
        bigint id PK
        varchar_20 codigo
        varchar_100 nombre
        varchar_50 tipo_insumo
        varchar_20 unidad_medida
        decimal_10_2 precio_unitario
        decimal_10_2 stock_actual
        decimal_10_2 stock_minimo
        int stock_sacos
        decimal_8_2 kilos_por_saco
        decimal_10_2 total_kg
        decimal_10_2 precio_saco
        varchar_150 proveedor_nombre
        varchar_150 producto_odepa
    }

    core_tipoenvase {
        bigint id PK
        varchar_100 nombre
    }

    core_envaseinsumo {
        bigint id PK
        varchar_50 tipo
        decimal_10_2 contenido
        decimal_10_2 restante
        decimal_10_2 precio
        datetime_6 fecha_ingreso
        bigint insumo_id FK
    }

    core_historialprecioinsumo {
        bigint id PK
        decimal_10_2 precio_saco
        decimal_10_2 precio_anterior
        decimal_6_2 variacion_porcentaje
        varchar_50 origen_cambio
        datetime_6 fecha_registro
        bigint insumo_id FK
    }

    core_preciomercado {
        bigint id PK
        varchar_50 fuente
        varchar_150 producto_fuente
        varchar_100 region
        varchar_100 sector
        varchar_100 tipo_punto
        date fecha
        varchar_50 unidad
        decimal_10_2 precio_minimo
        decimal_10_2 precio_maximo
        decimal_10_2 precio_promedio
        bigint insumo_id FK
    }

    core_proveedor {
        bigint id PK
        varchar_12 rut
        varchar_150 nombre_proveedor
        varchar_50 tipo_proveedor
        varchar_254 email
        varchar_20 telefono
        varchar_255 direccion
        decimal_10_2 costo_flete
        tinyint_1 activo
    }

    core_proveedorinsumo {
        bigint id PK
        decimal_10_2 precio_ofrecido
        bigint insumo_id FK
        bigint proveedor_id FK
    }

    core_ordencompra {
        bigint id PK
        varchar_30 codigo
        datetime_6 fecha_emision
        date fecha_entrega_esperada
        varchar_30 estado
        varchar_150 contacto_nombre
        varchar_254 contacto_email
        varchar_30 contacto_telefono
        decimal_10_2 costo_flete
        decimal_12_2 subtotal
        decimal_12_2 total
        varchar_150 condiciones_pago
        longtext observaciones
        tinyint_1 enviada_por_email
        datetime_6 fecha_envio_email
        tinyint_1 enviada_por_mensaje
        datetime_6 fecha_envio_mensaje
        bigint proveedor_id FK
        bigint usuario_id FK
    }

    core_detalleordencompra {
        bigint id PK
        int cantidad_sacos
        decimal_8_2 kilos_por_saco
        decimal_10_2 total_kilos
        decimal_10_2 precio_unitario
        decimal_12_2 subtotal
        bigint orden_compra_id FK
        bigint insumo_id FK
    }

    %% ====================================================
    %% 4. PRODUCCIÓN DIARIA, MERMAS Y ALERTAS
    %% ====================================================

    core_producciondiaria {
        bigint id PK
        int cantidad
        datetime_6 fecha_produccion
        bigint producto_id FK
        bigint responsable_id FK
    }

    core_consumoproduccion {
        bigint id PK
        varchar_100 nombre_insumo
        varchar_20 unidad
        decimal_10_3 cantidad_receta
        decimal_10_3 cantidad_usada
        decimal_10_3 faltante
        decimal_10_2 costo
        bigint produccion_id FK
        bigint insumo_id FK
    }

    core_merma {
        bigint id PK
        varchar_20 tipo
        varchar_150 nombre_item
        varchar_20 unidad
        decimal_10_3 cantidad
        varchar_50 motivo
        longtext detalle
        decimal_10_3 stock_anterior
        decimal_10_3 stock_resultante
        decimal_10_2 valor_estimado
        datetime_6 fecha
        bigint producto_id FK
        bigint insumo_id FK
        bigint envase_id FK
    }

    core_notificacion {
        bigint id PK
        varchar_30 tipo
        varchar_150 titulo
        longtext mensaje
        datetime_6 fecha_creacion
        tinyint_1 leida
        bigint producto_id FK
    }

    %% ====================================================
    %% 5. VENTAS E-COMMERCE Y POS (CARRITO, PEDIDOS Y PAGOS)
    %% ====================================================

    core_carrito {
        bigint id PK
        datetime_6 fecha_creacion
        bigint cliente_id FK
    }

    core_itemcarrito {
        bigint id PK
        int cantidad
        decimal_10_2 subtotal
        bigint carrito_id FK
        bigint producto_id FK
    }

    core_pedido {
        bigint id PK
        datetime_6 fecha
        varchar_50 estado
        varchar_50 canal
        varchar_50 tipo_entrega
        varchar_255 direccion_despacho
        varchar_150 cliente_nombre_respaldo
        decimal_10_2 subtotal_bruto
        decimal_10_2 descuento_puntos
        int puntos_canjeados
        int puntos_ganados
        decimal_10_2 total
        bigint cliente_id FK
        bigint cajero_id FK
    }

    core_detallepedido {
        bigint id PK
        int cantidad
        decimal_10_2 precio_unitario
        decimal_10_2 subtotal
        bigint pedido_id FK
        bigint producto_id FK
    }

    core_pago {
        bigint id PK
        decimal_10_2 monto
        varchar_50 metodo
        varchar_50 estado
        varchar_100 codigo_autorizacion
        datetime_6 fecha_pago
        bigint pedido_id FK
    }

    %% ====================================================
    %% 6. OPERACIÓN POS Y CAJA REGISTRADORA
    %% ====================================================

    core_caja {
        bigint id PK
        int numero
        varchar_50 turno
        datetime_6 fecha_apertura
        datetime_6 fecha_cierre
        decimal_10_2 monto_inicial
        varchar_20 estado
        longtext observacion_apertura
        bigint cajero_id FK
    }

    core_cierrecaja {
        bigint id PK
        decimal_10_2 monto_inicial
        decimal_10_2 monto_ventas_sistema
        decimal_10_2 monto_contado
        decimal_10_2 diferencia
        varchar_50 estado_cuadratura
        datetime_6 fecha_cierre
        longtext observacion
        bigint caja_id FK
    }

    %% ====================================================
    %% RELACIONES DEL MODELO DE DOMINIO
    %% ====================================================

    %% Perfiles herederos de Usuario (1 a 1 opcional)
    core_usuario ||--o| core_cliente : "perfil_cliente"
    core_usuario ||--o| core_cajero : "perfil_cajero"
    core_usuario ||--o| core_administrador : "perfil_admin"

    %% Cliente, Fidelización y Operaciones
    core_cliente ||--o| core_puntosfidelizacion : "acumula_puntos"
    core_cliente ||--o{ core_movimientopuntos : "registra_movimiento"
    core_pedido |o--o{ core_movimientopuntos : "origina_movimiento"
    core_cliente |o--o{ core_carrito : "abre_carrito"
    core_cliente |o--o{ core_pedido : "realiza_pedido"
    core_cajero |o--o{ core_pedido : "registra_venta_pos"

    %% Operación de Caja POS
    core_cajero |o--o{ core_caja : "administra_caja"
    core_caja ||--o| core_cierrecaja : "genera_cierre"

    %% Catálogo y Turnos
    core_categoria ||--o{ core_producto : "clasifica"
    core_producto ||--o{ core_producto_turnos : "asociado_a"
    core_turno ||--o{ core_producto_turnos : "aplica_en"

    %% Recetas e Insumos
    core_producto ||--o| core_receta : "elaborado_con"
    core_receta ||--o{ core_ingredientereceta : "requiere"
    core_insumo ||--o{ core_ingredientereceta : "usado_en"

    %% Envases, Precios Históricos y Mercado ODEPA
    core_insumo ||--o{ core_envaseinsumo : "almacenado_en"
    core_insumo ||--o{ core_historialprecioinsumo : "registra_variacion"
    core_insumo ||--o{ core_preciomercado : "referencia_odepa"

    %% Proveedores y Órdenes de Compra
    core_insumo ||--o{ core_proveedorinsumo : "cotizado_en"
    core_proveedor ||--o{ core_proveedorinsumo : "ofrece"
    core_proveedor ||--o{ core_ordencompra : "recibe_orden"
    core_usuario |o--o{ core_ordencompra : "emite_orden"
    core_ordencompra ||--o{ core_detalleordencompra : "detalla"
    core_insumo ||--o{ core_detalleordencompra : "solicitado_en"

    %% Registro de Producción, Consumos, Mermas y Alertas
    core_producto ||--o{ core_producciondiaria : "se_hornea"
    core_usuario |o--o{ core_producciondiaria : "registra_hornada"
    core_producciondiaria ||--o{ core_consumoproduccion : "consume"
    core_insumo |o--o{ core_consumoproduccion : "descontado_en"
    core_producto |o--o{ core_merma : "registra_merma_producto"
    core_insumo |o--o{ core_merma : "registra_merma_insumo"
    core_envaseinsumo |o--o{ core_merma : "registra_merma_envase"
    core_producto |o--o{ core_notificacion : "genera_alerta"

    %% Carrito de Compras
    core_carrito ||--o{ core_itemcarrito : "contiene"
    core_producto ||--o{ core_itemcarrito : "agregado_a"

    %% Pedido, Detalle y Pago (1 a 1)
    core_pedido ||--o{ core_detallepedido : "desglosa"
    core_producto ||--o{ core_detallepedido : "incluido_en"
    core_pedido ||--|| core_pago : "se_cancela_con"

erDiagram

    %% ====================================================
    %% 1. USUARIOS, PERFILES, FIDELIZACIÓN Y SEGURIDAD
    %% ====================================================

    core_usuario {
        bigint id PK
        varchar_128 password
        datetime_6 last_login
        tinyint_1 is_superuser
        varchar_150 username
        varchar_150 first_name
        varchar_150 last_name
        varchar_254 email
        tinyint_1 is_staff
        tinyint_1 is_active
        datetime_6 date_joined
        varchar_20 rol
    }

    core_cliente {
        bigint id PK
        varchar_255 direccion
        varchar_20 telefono
        bigint user_id FK
    }

    core_cajero {
        bigint id PK
        int num_caja_asignada
        varchar_50 jornada
        bigint user_id FK
    }

    core_administrador {
        bigint id PK
        varchar_50 nivel_acceso
        bigint user_id FK
    }

    core_puntosfidelizacion {
        bigint id PK
        int puntos_acumulados
        datetime_6 fecha_actualizacion
        bigint cliente_id FK
    }

    core_movimientopuntos {
        bigint id PK
        varchar_20 tipo
        int puntos
        int saldo_resultante
        varchar_255 descripcion
        datetime_6 fecha
        bigint cliente_id FK
        bigint pedido_id FK
    }

    %% ====================================================
    %% 2. CATÁLOGO, PRODUCTOS, TURNOS Y RECETAS
    %% ====================================================

    core_categoria {
        bigint id PK
        varchar_100 nombre
        longtext descripcion
        tinyint_1 es_horno
    }

    core_producto {
        bigint id PK
        varchar_150 nombre
        longtext descripcion
        decimal_10_2 precio
        int stock
        int stock_critico
        varchar_500 imagen_url
        tinyint_1 activo
        bigint categoria_id FK
        varchar_10 unidad_medida
        varchar_100 unidades_por_kg
    }

    core_turno {
        bigint id PK
        varchar_50 nombre
        time_6 hora_inicio
        time_6 hora_fin
        tinyint_1 lunes
        tinyint_1 martes
        tinyint_1 miercoles
        tinyint_1 jueves
        tinyint_1 viernes
        tinyint_1 sabado
        tinyint_1 domingo
        tinyint_1 activo
    }

    core_producto_turnos {
        bigint id PK
        bigint producto_id FK
        bigint turno_id FK
    }

    core_receta {
        bigint id PK
        varchar_150 nombre
        longtext descripcion
        bigint producto_id FK
    }

    core_ingredientereceta {
        bigint id PK
        decimal_10_3 cantidad
        bigint insumo_id FK
        bigint receta_id FK
    }

    %% ====================================================
    %% 3. MATERIAS PRIMAS, ENVASES, PRECIOS Y ABASTECIMIENTO
    %% ====================================================

    core_insumo {
        bigint id PK
        varchar_20 codigo
        varchar_100 nombre
        varchar_50 tipo_insumo
        varchar_20 unidad_medida
        decimal_10_2 precio_unitario
        decimal_10_2 stock_actual
        decimal_10_2 stock_minimo
        int stock_sacos
        decimal_8_2 kilos_por_saco
        decimal_10_2 total_kg
        decimal_10_2 precio_saco
        varchar_150 proveedor_nombre
        varchar_150 producto_odepa
    }

    core_tipoenvase {
        bigint id PK
        varchar_100 nombre
    }

    core_envaseinsumo {
        bigint id PK
        varchar_50 tipo
        decimal_10_2 contenido
        decimal_10_2 restante
        decimal_10_2 precio
        datetime_6 fecha_ingreso
        bigint insumo_id FK
    }

    core_historialprecioinsumo {
        bigint id PK
        decimal_10_2 precio_saco
        decimal_10_2 precio_anterior
        decimal_6_2 variacion_porcentaje
        varchar_50 origen_cambio
        datetime_6 fecha_registro
        bigint insumo_id FK
    }

    core_preciomercado {
        bigint id PK
        varchar_50 fuente
        varchar_150 producto_fuente
        varchar_100 region
        varchar_100 sector
        varchar_100 tipo_punto
        date fecha
        varchar_50 unidad
        decimal_10_2 precio_minimo
        decimal_10_2 precio_maximo
        decimal_10_2 precio_promedio
        bigint insumo_id FK
    }

    core_proveedor {
        bigint id PK
        varchar_12 rut
        varchar_150 nombre_proveedor
        varchar_50 tipo_proveedor
        varchar_254 email
        varchar_20 telefono
        varchar_255 direccion
        decimal_10_2 costo_flete
        tinyint_1 activo
    }

    core_proveedorinsumo {
        bigint id PK
        decimal_10_2 precio_ofrecido
        bigint insumo_id FK
        bigint proveedor_id FK
    }

    core_ordencompra {
        bigint id PK
        varchar_30 codigo
        datetime_6 fecha_emision
        date fecha_entrega_esperada
        varchar_30 estado
        varchar_150 contacto_nombre
        varchar_254 contacto_email
        varchar_30 contacto_telefono
        decimal_10_2 costo_flete
        decimal_12_2 subtotal
        decimal_12_2 total
        varchar_150 condiciones_pago
        longtext observaciones
        tinyint_1 enviada_por_email
        datetime_6 fecha_envio_email
        tinyint_1 enviada_por_mensaje
        datetime_6 fecha_envio_mensaje
        bigint proveedor_id FK
        bigint usuario_id FK
    }

    core_detalleordencompra {
        bigint id PK
        int cantidad_sacos
        decimal_8_2 kilos_por_saco
        decimal_10_2 total_kilos
        decimal_10_2 precio_unitario
        decimal_12_2 subtotal
        bigint orden_compra_id FK
        bigint insumo_id FK
    }

    %% ====================================================
    %% 4. PRODUCCIÓN DIARIA, MERMAS Y ALERTAS
    %% ====================================================

    core_producciondiaria {
        bigint id PK
        int cantidad
        datetime_6 fecha_produccion
        bigint producto_id FK
        bigint responsable_id FK
    }

    core_consumoproduccion {
        bigint id PK
        varchar_100 nombre_insumo
        varchar_20 unidad
        decimal_10_3 cantidad_receta
        decimal_10_3 cantidad_usada
        decimal_10_3 faltante
        decimal_10_2 costo
        bigint produccion_id FK
        bigint insumo_id FK
    }

    core_merma {
        bigint id PK
        varchar_20 tipo
        varchar_150 nombre_item
        varchar_20 unidad
        decimal_10_3 cantidad
        varchar_50 motivo
        longtext detalle
        decimal_10_3 stock_anterior
        decimal_10_3 stock_resultante
        decimal_10_2 valor_estimado
        datetime_6 fecha
        bigint producto_id FK
        bigint insumo_id FK
        bigint envase_id FK
    }

    core_notificacion {
        bigint id PK
        varchar_30 tipo
        varchar_150 titulo
        longtext mensaje
        datetime_6 fecha_creacion
        tinyint_1 leida
        bigint producto_id FK
    }

    %% ====================================================
    %% 5. VENTAS E-COMMERCE Y POS (CARRITO, PEDIDOS Y PAGOS)
    %% ====================================================

    core_carrito {
        bigint id PK
        datetime_6 fecha_creacion
        bigint cliente_id FK
    }

    core_itemcarrito {
        bigint id PK
        int cantidad
        decimal_10_2 subtotal
        bigint carrito_id FK
        bigint producto_id FK
    }

    core_pedido {
        bigint id PK
        datetime_6 fecha
        varchar_50 estado
        varchar_50 canal
        varchar_50 tipo_entrega
        varchar_255 direccion_despacho
        varchar_150 cliente_nombre_respaldo
        decimal_10_2 subtotal_bruto
        decimal_10_2 descuento_puntos
        int puntos_canjeados
        int puntos_ganados
        decimal_10_2 total
        bigint cliente_id FK
        bigint cajero_id FK
    }

    core_detallepedido {
        bigint id PK
        int cantidad
        decimal_10_2 precio_unitario
        decimal_10_2 subtotal
        bigint pedido_id FK
        bigint producto_id FK
    }

    core_pago {
        bigint id PK
        decimal_10_2 monto
        varchar_50 metodo
        varchar_50 estado
        varchar_100 codigo_autorizacion
        datetime_6 fecha_pago
        bigint pedido_id FK
    }

    %% ====================================================
    %% 6. OPERACIÓN POS Y CAJA REGISTRADORA
    %% ====================================================

    core_caja {
        bigint id PK
        int numero
        varchar_50 turno
        datetime_6 fecha_apertura
        datetime_6 fecha_cierre
        decimal_10_2 monto_inicial
        varchar_20 estado
        longtext observacion_apertura
        bigint cajero_id FK
    }

    core_cierrecaja {
        bigint id PK
        decimal_10_2 monto_inicial
        decimal_10_2 monto_ventas_sistema
        decimal_10_2 monto_contado
        decimal_10_2 diferencia
        varchar_50 estado_cuadratura
        datetime_6 fecha_cierre
        longtext observacion
        bigint caja_id FK
    }

    %% ====================================================
    %% 7. TABLAS INTERNAS Y AUTENTICACIÓN DJANGO (AUTH & SYSTEM)
    %% ====================================================

    auth_group {
        int id PK
        varchar_150 name
    }

    auth_permission {
        int id PK
        varchar_255 name
        int content_type_id FK
        varchar_100 codename
    }

    auth_group_permissions {
        bigint id PK
        int group_id FK
        int permission_id FK
    }

    core_usuario_groups {
        bigint id PK
        bigint usuario_id FK
        int group_id FK
    }

    core_usuario_user_permissions {
        bigint id PK
        bigint usuario_id FK
        int permission_id FK
    }

    django_content_type {
        int id PK
        varchar_100 app_label
        varchar_100 model
    }

    django_admin_log {
        int id PK
        datetime_6 action_time
        longtext object_id
        varchar_200 object_repr
        smallint_unsigned action_flag
        longtext change_message
        int content_type_id FK
        bigint user_id FK
    }

    django_migrations {
        bigint id PK
        varchar_255 app
        varchar_255 name
        datetime_6 applied
    }

    django_session {
        varchar_40 session_key PK
        longtext session_data
        datetime_6 expire_date
    }

    %% ====================================================
    %% RELACIONES DEL MODELO FÍSICO COMPLETO
    %% ====================================================

    %% Perfiles y Usuarios
    core_usuario ||--o| core_cliente : "perfil_cliente"
    core_usuario ||--o| core_cajero : "perfil_cajero"
    core_usuario ||--o| core_administrador : "perfil_admin"

    %% Cliente, Fidelización y Ventas
    core_cliente ||--o| core_puntosfidelizacion : "acumula_puntos"
    core_cliente ||--o{ core_movimientopuntos : "registra_movimiento"
    core_pedido |o--o{ core_movimientopuntos : "origina_movimiento"
    core_cliente |o--o{ core_carrito : "posee_carrito"
    core_cliente |o--o{ core_pedido : "realiza_pedido"
    core_cajero |o--o{ core_pedido : "registra_venta_pos"

    %% Caja y POS
    core_cajero |o--o{ core_caja : "opera_caja"
    core_caja ||--o| core_cierrecaja : "audita_cierre"

    %% Catálogo, Turnos y Recetas
    core_categoria ||--o{ core_producto : "clasifica"
    core_producto ||--o{ core_producto_turnos : "asignado_a"
    core_turno ||--o{ core_producto_turnos : "aplica_en"
    core_producto ||--o| core_receta : "elaborado_con"
    core_receta ||--o{ core_ingredientereceta : "requiere"
    core_insumo ||--o{ core_ingredientereceta : "usado_como_ingrediente"

    %% Envases, Precios Históricos y Mercado ODEPA
    core_insumo ||--o{ core_envaseinsumo : "almacenado_en"
    core_insumo ||--o{ core_historialprecioinsumo : "registra_variacion"
    core_insumo ||--o{ core_preciomercado : "referencia_odepa"

    %% Proveedores y Órdenes de Compra
    core_insumo ||--o{ core_proveedorinsumo : "cotizado_en"
    core_proveedor ||--o{ core_proveedorinsumo : "suministra"
    core_proveedor ||--o{ core_ordencompra : "recibe_orden"
    core_usuario |o--o{ core_ordencompra : "emite_orden"
    core_ordencompra ||--o{ core_detalleordencompra : "detalla"
    core_insumo ||--o{ core_detalleordencompra : "solicitado_en"

    %% Producción, Consumos, Mermas y Alertas
    core_producto ||--o{ core_producciondiaria : "se_hornea"
    core_usuario |o--o{ core_producciondiaria : "registra_hornada"
    core_producciondiaria ||--o{ core_consumoproduccion : "consume"
    core_insumo |o--o{ core_consumoproduccion : "descontado_en"
    core_producto |o--o{ core_merma : "registra_merma_producto"
    core_insumo |o--o{ core_merma : "registra_merma_insumo"
    core_envaseinsumo |o--o{ core_merma : "registra_merma_envase"
    core_producto |o--o{ core_notificacion : "genera_alerta"

    %% Carrito
    core_carrito ||--o{ core_itemcarrito : "contiene"
    core_producto ||--o{ core_itemcarrito : "agregado_en"

    %% Ventas y Pago
    core_pedido ||--o{ core_detallepedido : "desglosa"
    core_producto ||--o{ core_detallepedido : "vendido_en"
    core_pedido ||--|| core_pago : "se_cancela_con"

    %% Framework Django Auth & Security
    core_usuario ||--o{ core_usuario_groups : "pertenece_a_grupo"
    auth_group ||--o{ core_usuario_groups : "grupo_asignado"

    core_usuario ||--o{ core_usuario_user_permissions : "posee_permiso"
    auth_permission ||--o{ core_usuario_user_permissions : "permiso_directo"

    auth_group ||--o{ auth_group_permissions : "contiene_permisos"
    auth_permission ||--o{ auth_group_permissions : "otorgado_a_grupo"

    django_content_type ||--o{ auth_permission : "define_modelo_de_permiso"
    django_content_type |o--o{ django_admin_log : "registra_modelo_modificado"
    core_usuario ||--o{ django_admin_log : "registra_accion_admin"
