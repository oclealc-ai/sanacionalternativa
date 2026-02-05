-- ================================================================
-- MIGRACIÓN: Agregar soporte multiempresa a tabla paciente
-- ================================================================
-- 
-- Esta migración agrega la columna idEmpresa a la tabla paciente
-- para permitir que el mismo teléfono exista en múltiples empresas.
--
-- IMPORTANTE: Ejecutar esta migración ANTES de usar el nuevo sistema
-- ================================================================

-- 1. Agregar columna idEmpresa si no existe
-- (Si la columna YA existe, puedes comentar esta línea)
ALTER TABLE paciente
ADD COLUMN idEmpresa INT DEFAULT 1 NOT NULL,
ADD CONSTRAINT fk_paciente_empresa 
    FOREIGN KEY (idEmpresa) REFERENCES Empresa(idEmpresa) ON DELETE CASCADE;

-- 2. Si tenías pacientes previos, necesitas asignarlos a una empresa
-- Por ejemplo, si "Sanacion Alternativa" es la empresa 1:
-- UPDATE paciente SET idEmpresa = 1 WHERE idEmpresa IS NULL;

-- 3. Crear índice para búsquedas rápidas (teléfono + empresa)
CREATE UNIQUE INDEX idx_paciente_telefono_empresa 
ON paciente(telefono, idEmpresa);

-- 4. Verificar que todo esté bien
-- SELECT * FROM paciente LIMIT 5;
-- SELECT * FROM information_schema.COLUMNS WHERE TABLE_NAME='paciente' AND COLUMN_NAME='idEmpresa';

-- ================================================================
-- Cambios en las rutas de paciente:
-- ================================================================
-- ✅ Login: /empresa/{idEmpresa}/paciente/login
-- ✅ Alta: /empresa/{idEmpresa}/paciente/alta
-- ✅ Menú: /empresa/{idEmpresa}/paciente/menu
-- ✅ API login: POST /paciente/empresa/{idEmpresa}/auth/login
-- ✅ API validar: POST /paciente/validar_codigo_empresa
-- ================================================================
