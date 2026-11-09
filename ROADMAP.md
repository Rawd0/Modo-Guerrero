# Hoja de ruta

Mejoras previstas para próximas versiones. No están en orden estricto.

## Varios usuarios en la misma instalación

Que varias personas puedan usar la misma app en el mismo servidor, cada una con su cuenta
de Garmin y sus datos separados.

Puntos a resolver:

- ~~**Inicio de sesión propio en la app.**~~ Hecho en la 0.2.0 (usuarios, sesiones, recordar dispositivo).
- **Un administrador** que crea, edita y elimina usuarios (el primer usuario ya se crea al arrancar
  la app por primera vez).
- **Datos separados por usuario.** Columna `user_id` en actividades, detalle de carreras,
  mejores esfuerzos, salud diaria, estado de forma, ajustes y registro de sincronización.
  Cada consulta filtra siempre por el usuario de la sesión.
- **Cuenta de Garmin por usuario**, con su propio token cifrado y su propio flujo de verificación
  en dos pasos.
- **Ajustes por usuario:** objetivos, FC máxima y en reposo, widgets del inicio.
- **Sincronización:** el programador recorre los usuarios uno a uno, con pausas, para no
  multiplicar las peticiones a Garmin a la vez.
- **Migración:** los datos actuales pasan a pertenecer al primer usuario sin perder nada.
- **Privacidad:** ningún usuario puede ver los datos de otro, tampoco el administrador salvo que
  se decida lo contrario.

## Face ID con passkeys

Iniciar sesión con Face ID / huella mediante passkeys (WebAuthn). Requiere entrar por HTTPS con un
nombre de dominio: la opción prevista son los certificados HTTPS de Tailscale
(`https://<servidor>.<red>.ts.net`). La contraseña quedaría como respaldo.

## Otras mejoras pendientes

- **Botón «No me llega el código»** en la verificación en dos pasos: mostrar por dónde dice Garmin
  que ha enviado el código y reintentar por el método web, que pide explícitamente el envío.
- **Strava** como fuente complementaria (segmentos, kudos) o alternativa a Garmin.
- **Inicio con cuadrícula libre:** widgets redimensionables y nuevos widgets (objetivos, calendario
  del mes, comparativa con el año anterior, sueño frente a rendimiento).
- **Preguntas en lenguaje natural** sobre tus datos usando un modelo local (Ollama).
- **Objetivos y preparación de carreras:** fecha de la carrera, plan y seguimiento.
