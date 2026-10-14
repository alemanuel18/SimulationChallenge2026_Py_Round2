# Banco de pruebas para la ronda oculta

El banco crea diez escenarios locales y reproducibles. Cada carpeta contiene
su manifiesto, el baseline correspondiente y una subcarpeta `results` para que
las corridas no se mezclen. Todo `hidden_round_cases/` está ignorado por Git.

Los casos cambian disrupciones, demanda, flota, capacidad, velocidad, atraques,
horarios, identificadores de rutas y, en un caso, la topología disponible. No
se modifican `Input/`, `scenario_builders/` ni el motor de simulación.

## Comandos

Preparar o reconstruir las carpetas locales:

```bash
.venv/bin/python response_strategies/optimize_round2.py --prepare-cases
```

Validar rápidamente los diez procesos con una simulación corta:

```bash
.venv/bin/python response_strategies/optimize_round2.py --smoke --workers 10
```

Medir una vez los valores actuales con los 140 días de calentamiento y los 360
días oficiales:

```bash
.venv/bin/python response_strategies/optimize_round2.py --evaluate-default --workers 10
```

Iniciar Optuna en segundo plano, sin límite de ensayos:

```bash
.venv/bin/python response_strategies/optimize_round2.py --daemon --workers 10
```

Consultar o detener la búsqueda:

```bash
.venv/bin/python response_strategies/optimize_round2.py --status
.venv/bin/python response_strategies/optimize_round2.py --best-history 10
.venv/bin/python response_strategies/optimize_round2.py --stop
```

Para limitar una ejecución, agregar `--trials N`. Si la memoria disponible no
permite diez procesos simultáneos, reducir `--workers` no cambia el resultado,
solamente el tiempo de ejecución.

Una corrida completa es deliberadamente pesada. En la máquina de desarrollo,
los baselines tardaron aproximadamente entre 13 y 23 minutos cada uno cuando
se ejecutaron los diez a la vez; quedan cacheados. Los escenarios con mayor
congestión pueden tardar bastante más. Cada resultado se guarda en cuanto su
proceso termina, aunque otro caso continúe trabajando o la corrida se
interrumpa.

Cada caso tiene un límite predeterminado de 7200 segundos (dos horas). Si una combinación
produce congestión explosiva y excede ese tiempo, recibe `loss=1000` y la
búsqueda continúa. Puede cambiarse con `--case-timeout-seconds SEGUNDOS`.

## Selección robusta

Cada candidato usa exactamente los mismos parámetros en los diez escenarios.
La función objetivo es:

```text
promedio(loss) + 0.35 * desviación + 0.25 * (peor_loss - promedio)
```

El último término nunca es negativo. Esto evita favorecer una combinación que
obtenga un resultado excelente en algunos casos a costa de fallar gravemente
en otro. Un error de simulación recibe un loss de 1000, por lo que una
configuración frágil no puede convertirse accidentalmente en la mejor.

La búsqueda ajusta únicamente parámetros independientes de nombres concretos
de rutas: espera, operación portuaria, prioridad de atraque, beneficio mínimo
de desvíos, anticipación basada en headway y umbrales de bypass. Los antiguos
interruptores específicos de S1, S4, S5, S7 y S9 no participan.

## Archivos locales

- `hidden_round_cases/case_*/scenario.json`: definición legible del caso.
- `hidden_round_cases/case_*/baseline_*.json`: baseline cacheado de esa red.
- `hidden_round_cases/case_*/results/*.json`: loss, ATT y parámetros por caso.
- `optuna_state/hidden_round.db`: estudio reanudable.
- `optuna_state/hidden_round_best.json`: mejor combinación consolidada.
- `optuna_state/hidden_round_optimizer.log`: progreso del daemon.

Los valores ganadores todavía deben promoverse como defaults de
`round2_strategy.py` antes de preparar la entrega final; el evaluador oculto no
debe suponerse configurado con nuestras variables de entorno.
