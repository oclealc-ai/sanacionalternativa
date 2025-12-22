CREATE DATABASE  IF NOT EXISTS `sanalter` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;
USE `sanalter`;
-- MySQL dump 10.13  Distrib 8.0.44, for Win64 (x86_64)
--
-- Host: localhost    Database: sanalter
-- ------------------------------------------------------
-- Server version	9.5.0

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
SET @MYSQLDUMP_TEMP_LOG_BIN = @@SESSION.SQL_LOG_BIN;
SET @@SESSION.SQL_LOG_BIN= 0;

--
-- GTID state at the beginning of the backup 
--

SET @@GLOBAL.GTID_PURGED=/*!80000 '+'*/ '6a4ed3bd-b504-11f0-95e3-5065f341d288:1-418';

--
-- Table structure for table `citas`
--

DROP TABLE IF EXISTS `citas`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `citas` (
  `idCita` int NOT NULL AUTO_INCREMENT,
  `Terapeuta` varchar(10) DEFAULT NULL,
  `idPaciente` int DEFAULT NULL,
  `Para` varchar(45) DEFAULT NULL COMMENT 'Es el nombre de la persona que tomara realmente la terapia',
  `FechaSolicitud` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `FechaCita` date NOT NULL,
  `HoraCita` time NOT NULL,
  `Duracion` int DEFAULT NULL,
  `Notas` varchar(255) DEFAULT NULL,
  `Estatus` enum('Disponible','Reservada','Confirmada','Cancelada','Realizada','Bloqueada') DEFAULT 'Disponible' COMMENT 'disponible: cuando esta libre de que un paciente la pueda tomar\\\\\\\\nconfirmada: cuando un paciente confirma que si asistirá a la cita\\\\\\\\ncancelada: cuando un paciente cancela su cita\\\\\\\\nrealizada: cuando el paciente si asistió y la cita se realizó\\\\\\\\ncerrada: cuando un administrador o asistente cierra la cita para que nadie pueda tomarla',
  PRIMARY KEY (`idCita`),
  KEY `citas_ibfk_1` (`idPaciente`),
  KEY `idx_terapeuta_fecha` (`Terapeuta`,`FechaCita`,`HoraCita`),
  CONSTRAINT `citas_ibfk_1` FOREIGN KEY (`idPaciente`) REFERENCES `paciente` (`idPaciente`)
) ENGINE=InnoDB AUTO_INCREMENT=6304 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `codigos_telefono`
--

DROP TABLE IF EXISTS `codigos_telefono`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `codigos_telefono` (
  `telefono` varchar(20) NOT NULL,
  `codigo` varchar(6) DEFAULT NULL,
  `expiracion` datetime DEFAULT NULL,
  PRIMARY KEY (`telefono`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `frases`
--

DROP TABLE IF EXISTS `frases`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `frases` (
  `idFrase` int NOT NULL AUTO_INCREMENT,
  `fecha` date NOT NULL,
  `frase` varchar(200) DEFAULT NULL,
  PRIMARY KEY (`idFrase`)
) ENGINE=InnoDB AUTO_INCREMENT=23 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `historial_citas`
--

DROP TABLE IF EXISTS `historial_citas`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `historial_citas` (
  `IdHistorial` int NOT NULL AUTO_INCREMENT,
  `IdCita` int NOT NULL,
  `Fecha` date NOT NULL,
  `Hora` time NOT NULL,
  `Usuario` varchar(100) NOT NULL,
  `Estatus` varchar(50) NOT NULL,
  `Comentario` text,
  PRIMARY KEY (`IdHistorial`),
  KEY `IdCita` (`IdCita`),
  CONSTRAINT `historial_citas_ibfk_1` FOREIGN KEY (`IdCita`) REFERENCES `citas` (`idCita`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `paciente`
--

DROP TABLE IF EXISTS `paciente`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `paciente` (
  `idPaciente` int NOT NULL AUTO_INCREMENT,
  `Password` varchar(45) DEFAULT NULL,
  `NombrePaciente` varchar(80) DEFAULT NULL,
  `FechaNac` date DEFAULT NULL,
  `Telefono` varchar(20) DEFAULT NULL,
  `Correo` varchar(45) NOT NULL,
  `Direccion` varchar(100) DEFAULT NULL,
  `Ciudad` varchar(15) DEFAULT NULL,
  `Estado` varchar(15) DEFAULT NULL,
  `Pais` varchar(15) DEFAULT NULL,
  `Referencia` int DEFAULT NULL,
  `Fallecido` tinyint(1) NOT NULL DEFAULT '0',
  `FechaFall` date DEFAULT NULL,
  `CorreoValido` tinyint(1) DEFAULT '0',
  `TokenCorreoVerificacion` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`idPaciente`),
  UNIQUE KEY `Telefono_UNIQUE` (`Telefono`),
  FULLTEXT KEY `xNombre` (`NombrePaciente`)
) ENGINE=InnoDB AUTO_INCREMENT=35 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `usuarios`
--

DROP TABLE IF EXISTS `usuarios`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `usuarios` (
  `IdUsuario` int NOT NULL AUTO_INCREMENT,
  `Usuario` varchar(10) NOT NULL,
  `NombreUsuario` varchar(45) DEFAULT NULL,
  `Password` varchar(255) NOT NULL,
  `TipoUsuario` enum('admin','terapeuta','asistente') NOT NULL DEFAULT 'asistente',
  PRIMARY KEY (`IdUsuario`),
  UNIQUE KEY `Usuario` (`Usuario`)
) ENGINE=InnoDB AUTO_INCREMENT=13 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
SET @@SESSION.SQL_LOG_BIN = @MYSQLDUMP_TEMP_LOG_BIN;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2025-12-19 17:28:05
