-- ================================================================
-- MIGRACIÓN: Configurar índice único para pacientes multiempresa
-- ================================================================
-- 
-- La columna idEmpresa YA EXISTE en la tabla paciente.
-- Solo necesitamos crear el índice único que permite el mismo
-- teléfono en diferentes empresas.
--
-- IMPORTANTE: Ejecutar esta migración para optimizar búsquedas
-- ================================================================

-- 1. CREAR ÍNDICE ÚNICO para búsquedas rápidas (Telefono + idEmpresa)
-- Esto permite el MISMO Telefono en diferentes empresas
-- pero evita duplicados dentro de la misma empresa

-- Primero, DROP el índice anterior si existe
DROP INDEX IF EXISTS idx_paciente_telefono ON paciente;

-- Luego crear el nuevo índice compuesto
CREATE UNIQUE INDEX idx_paciente_telefono_empresa 
ON paciente(Telefono, idEmpresa);

-- 2. OPCIONALMENTE: Investigar si la columna "Empresa" es duplicada
-- Si "Empresa" e "idEmpresa" son iguales, se puede eliminar "Empresa":
-- ALTER TABLE paciente DROP COLUMN Empresa;
-- (CUIDADO: solo si están duplicados - verificar primero)

-- 3. VERIFICAR QUE TODO ESTÉ BIEN
-- SELECT * FROM paciente LIMIT 5;
-- SHOW INDEXES FROM paciente;
-- SELECT * FROM information_schema.COLUMNS WHERE TABLE_NAME='paciente';

-- ================================================================
-- Cambios en las rutas de paciente:
-- ================================================================
-- ✅ Login: /empresa/{idEmpresa}/paciente/login
-- ✅ Alta: /empresa/{idEmpresa}/paciente/alta  
-- ✅ Menú: /empresa/{idEmpresa}/paciente/menu
-- ✅ API login: POST /paciente/empresa/{idEmpresa}/auth/login
-- ✅ API validar: POST /paciente/validar_codigo_empresa
-- ================================================================
