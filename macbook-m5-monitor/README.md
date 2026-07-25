# Monitor de ofertas MacBook Pro M5

Este proyecto revisa páginas de producto mediante Playwright y envía un correo
cuando encuentra una MacBook Pro M5 nueva con precio igual o menor al límite
definido en `stores.json`.

## Configuración rápida

1. Sustituye las URL de ejemplo de `stores.json` por URL directas de productos.
2. En GitHub, abre Settings > Secrets and variables > Actions.
3. Crea estos Repository secrets:
   - `SMTP_USER`: cuenta Gmail remitente.
   - `SMTP_APP_PASSWORD`: contraseña de aplicación de Google, sin espacios.
   - `EMAIL_TO`: correo que recibirá los avisos.
4. Abre Actions > Monitor MacBook Pro M5 > Run workflow.
5. Mantén activada la opción de correo de prueba y ejecuta.
6. Comprueba tu bandeja de entrada y Spam.
7. Las ejecuciones programadas correrán cada hora.

## Notas importantes

- Usa URL directas de cada producto, no páginas generales de búsqueda.
- El detector busca datos estructurados JSON-LD y precios visibles.
- Algunas tiendas pueden bloquear automatizaciones o modificar su página.
- Un precio detectado debe confirmarse en la tienda antes de pagar.
- El script evita repetir exactamente la misma URL y precio mediante `state.json`.
- Para detenerlo, desactiva el workflow desde la pestaña Actions.

## Ajustar frecuencia

En `.github/workflows/monitor.yml`, modifica:

```yaml
- cron: "17 * * * *"
```

GitHub usa UTC y las ejecuciones programadas pueden retrasarse cuando hay mucha
carga. No se recomienda programarlas exactamente al inicio de la hora.
