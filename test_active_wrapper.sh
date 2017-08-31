export ELASTICSEARCH_HOST=localhost:9200
export PG_HOST=localhost:5432
export PG_USER=test
export PG_PASS=test
export PG_NAME=automated_test
export ES_USER=''
export ES_PASSWORD=''
CUR_DIR=$PWD
cd ./bin/
python set_project_released_states.py ACTIVE
cd $CUR_DIR
echo $@
exec python bin/build_active_graph_index.py $@
