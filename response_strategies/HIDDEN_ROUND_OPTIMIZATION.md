# Iterador para preparar la ronda oculta

Esta guía explica cómo preparar el entorno, levantar el iterador, consultar su
progreso, detenerlo y reanudarlo. Todos los comandos deben ejecutarse desde la
raíz de `SimulationChallenge2026_Py_Round2`.

El banco usa diez escenarios locales. Cada uno tiene su propia carpeta,
baseline y resultados. Las carpetas generadas, la base de datos de Optuna y
los logs están ignorados por Git.

## 1. Requisitos

- Python 3.10 o posterior.
- Algunos GB libres para la base de datos, baselines y resultados de muchas
  iteraciones. El espacio exacto depende de cuánto tiempo se deje trabajando.
- Diez núcleos o hilos disponibles para usar `--workers 10`. Puede utilizarse
  una cantidad menor si el equipo tiene menos memoria o CPU.
- Dependencias declaradas en `requirements.txt`, incluida Optuna.

No es necesario modificar `Input/`, `scenario_builders/`, `simulation_model/`
ni `main.py`.

## 2. Entrar al proyecto

La ruta contiene espacios, por lo que debe escribirse entre comillas:

```bash
cd "SimulationChallenge2026_Py_Round2"
```

## 3. Crear el entorno virtual

Este paso solo se realiza una vez:

```bash
python3 -m venv .venv
```

En algunos equipos el comando disponible puede llamarse `python`:

```bash
python -m venv .venv
```

## 4. Activar el entorno virtual

Linux o macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Windows CMD:

```bat
.venv\Scripts\activate.bat
```

Cuando esté activo, normalmente aparecerá `(.venv)` al inicio de la terminal.
También es posible omitir la activación y usar `.venv/bin/python` en cada
comando, como se hace en esta guía.

## 5. Instalar las dependencias

```bash
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

En Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Comprobar que Python y Optuna estén disponibles:

```bash
.venv/bin/python --version
.venv/bin/python -c "import optuna; print(optuna.__version__)"
```

## 6. Comprobar las pruebas

Antes de iniciar una búsqueda larga:

```bash
.venv/bin/python -m pytest response_strategies/tests -q
```

El resultado esperado actualmente es `14 passed`.

## 7. Preparar los diez escenarios

```bash
.venv/bin/python response_strategies/optimize_round2.py --prepare-cases
```

Esto crea:

```text
response_strategies/hidden_round_cases/
├── case_01_long_ocean_detours/
├── case_02_central_hub_closure/
├── ...
└── case_10_compound_late_crisis/
```

Cada carpeta contiene `scenario.json`, sus baselines cacheados y `results/`.
El comando puede repetirse sin afectar el código entregable.

## 8. Ejecutar la prueba corta

Antes del iterador completo, verificar que los diez procesos puedan levantarse:

```bash
.venv/bin/python response_strategies/optimize_round2.py --smoke --workers 10
```

Esta prueba usa solamente 5 días de calentamiento y 15 días medidos. No busca
parámetros y no sustituye la evaluación completa. El resultado validado fue:

```text
smoke robust_score=-0.046681
```

## 9. Evaluar los parámetros actuales

Para ejecutar una referencia completa sin iniciar Optuna:

```bash
.venv/bin/python response_strategies/optimize_round2.py \
  --evaluate-default \
  --workers 10
```

Usa 140 días de calentamiento, 360 días medidos e intervalos de 5 días. Los
baselines se calculan una vez y después se reutilizan.

## 10. Levantar el iterador en segundo plano

Esta es la forma recomendada para dejarlo trabajando durante varias horas:

```bash
.venv/bin/python response_strategies/optimize_round2.py \
  --daemon \
  --workers 10
```

Sin `--trials`, la búsqueda no tiene un número máximo de iteraciones. Continúa
hasta que se ejecute `--stop`, se apague el equipo o ocurra un error fatal.

Para ejecutar, por ejemplo, exactamente 20 iteraciones:

```bash
.venv/bin/python response_strategies/optimize_round2.py \
  --daemon \
  --workers 10 \
  --trials 20
```

El daemon imprime su PID y las rutas del log y del mejor resultado. No cierre
el proceso con `kill -9`; use el comando `--stop` para una terminación normal.

## 11. Ejecutarlo en primer plano

Esto permite ver los resultados directamente en la terminal:

```bash
.venv/bin/python response_strategies/optimize_round2.py \
  --trials 1 \
  --workers 10
```

Si se omite `--trials`, también busca indefinidamente, pero la terminal queda
ocupada. En primer plano puede detenerse después del ensayo actual con
`Ctrl+C`; los ensayos ya terminados permanecen en la base de datos.

`--worker` es una opción interna utilizada por `--daemon`. No debe ejecutarse
manualmente en el uso normal.

## 12. Consultar el estado

```bash
.venv/bin/python response_strategies/optimize_round2.py --status
```

Muestra:

- PID del daemon.
- Si el proceso sigue activo.
- Mejor score robusto.
- Parámetros de la mejor iteración.
- Loss de cada uno de los diez casos.
- Ruta del archivo de log.

Para observar el log en vivo en Linux o macOS:

```bash
tail -f response_strategies/optuna_state/hidden_round_optimizer.log
```

Salir de `tail` no detiene el iterador; se sale con `Ctrl+C`.

## 13. Consultar el historial de mejoras

Mostrar las últimas diez iteraciones que establecieron un nuevo récord:

```bash
.venv/bin/python response_strategies/optimize_round2.py --best-history
```

Solicitar otra cantidad, por ejemplo 25:

```bash
.venv/bin/python response_strategies/optimize_round2.py --best-history 25
```

## 14. Repetir el mejor resultado o una iteración

Volver a ejecutar el mejor conjunto de parámetros en los diez escenarios:

```bash
.venv/bin/python response_strategies/optimize_round2.py \
  --run-best \
  --workers 10
```

Repetir una iteración concreta, por ejemplo la número 17:

```bash
.venv/bin/python response_strategies/optimize_round2.py \
  --run-trial 17 \
  --workers 10
```

Estos comandos requieren que el estudio ya exista.

## 15. Detener y reanudar

Detener el daemon:

```bash
.venv/bin/python response_strategies/optimize_round2.py --stop
```

Para reanudarlo posteriormente se utiliza el mismo comando inicial:

```bash
.venv/bin/python response_strategies/optimize_round2.py \
  --daemon \
  --workers 10
```

Optuna abre `hidden_round.db` y continúa el mismo estudio. Los ensayos
terminados y el mejor resultado no se pierden si se cierra la terminal o se
reinicia el equipo.

## 16. Opciones configurables

Mostrar la ayuda incorporada:

```bash
.venv/bin/python response_strategies/optimize_round2.py --help
```

Opciones principales:

| Opción | Valor predeterminado | Función |
|---|---:|---|
| `--workers` | `10` | Cantidad máxima de escenarios simultáneos. |
| `--trials` | Sin límite | Número de combinaciones que probará Optuna. |
| `--seed` | `2026` | Semilla reproducible de las simulaciones. |
| `--warmup-days` | `140` | Días de calentamiento por simulación. |
| `--simulation-days` | `360` | Días medidos por simulación. |
| `--interval-days` | `5` | Tamaño de cada intervalo del loss. |
| `--case-timeout-seconds` | `3600` | Máximo de una hora por escenario. |

Ejemplo con cuatro procesos y máximo de una hora:

```bash
.venv/bin/python response_strategies/optimize_round2.py \
  --daemon \
  --workers 4 \
  --case-timeout-seconds 3600
```

Reducir `--workers` cambia el tiempo total, pero no la lógica ni los parámetros
evaluados. No conviene cambiar semilla, calentamiento, duración o intervalo a
mitad de un mismo estudio porque los scores dejarían de ser directamente
comparables.

## 17. Cómo se detiene una iteración problemática

Los diez casos empiezan en paralelo. Cada uno dispone de un máximo de 3,600
segundos. Si uno o más escenarios superan ese límite:

1. Se conservan los resultados de los casos que terminaron.
2. Los pendientes son detenidos.
3. Cada caso pendiente recibe `loss=1000` como penalización interna.
4. Optuna registra la combinación como poco conveniente.
5. Comienza la siguiente iteración automáticamente.

`loss=1000` no es un resultado oficial. Solo evita que una combinación lenta o
inestable paralice la búsqueda.

## 18. Cómo se selecciona el mejor candidato

Cada candidato utiliza los mismos parámetros en los diez escenarios. Su score
es:

```text
promedio(loss) + 0.35 × desviación + 0.25 × (peor loss - promedio)
```

El último término nunca puede ser negativo. Así se penalizan configuraciones
que funcionan bien en varios casos, pero fallan gravemente en uno.

Un loss negativo significa que el resultado calculado fue negativo porque el
ATT con estrategia fue menor que el baseline. No representa una
reducción directa de esa cantidad de días.

## 19. Archivos generados

- `hidden_round_cases/case_*/scenario.json`: definición de cada caso.
- `hidden_round_cases/case_*/baseline_*.json`: baseline cacheado.
- `hidden_round_cases/case_*/results/*.json`: loss, ATT y parámetros.
- `optuna_state/hidden_round.db`: estudio reanudable de Optuna.
- `optuna_state/hidden_round_best.json`: mejor combinación encontrada.
- `optuna_state/hidden_round_optimizer.log`: salida del daemon.
- `optuna_state/hidden_round_optimizer.pid`: PID mientras está activo.

Los resultados se escriben apenas termina cada escenario. Si una corrida se
interrumpe, los casos ya completados permanecen guardados.

## 20. Preparar finalmente la entrega

El archivo `hidden_round_best.json` usa variables de entorno para describir la
mejor combinación. Antes de entregar:

1. Repetir el mejor trial con `--run-best`.
2. Confirmar que no depende de uno solo de los diez escenarios.
3. Incorporar sus valores como defaults en `round2_strategy.py`.
4. Ejecutar nuevamente las pruebas.
5. Entregar únicamente los archivos permitidos de `response_strategies`.

No debe suponerse que el evaluador secreto configurará nuestras variables de
entorno.

## 21. Desactivar el entorno virtual

Al terminar el trabajo en la terminal:

```bash
deactivate
```
