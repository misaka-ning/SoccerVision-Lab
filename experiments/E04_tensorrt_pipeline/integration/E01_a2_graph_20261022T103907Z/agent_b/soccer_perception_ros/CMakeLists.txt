cmake_minimum_required(VERSION 3.8)
project(soccer_perception_ros)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

# Python code belongs in site-packages; ament supplies the import environment hook.
ament_python_install_package(soccer_perception)

install(PROGRAMS scripts/soccer_perception_ros_node.py
  DESTINATION lib/${PROJECT_NAME}
)

# Models are mutable deployment data, shared by source and installed execution.
# Record their location; never copy PT/ONNX/engine files into install/.
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/source_models_directory.txt"
  "${CMAKE_CURRENT_SOURCE_DIR}/models\n")
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/source_models_directory.txt"
  DESTINATION share/${PROJECT_NAME}
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE
  PATTERN "*.pyc" EXCLUDE
  PATTERN "*.engine" EXCLUDE
)

if(BUILD_TESTING)
  find_package(ament_cmake_test REQUIRED)
  ament_add_test(perception_unit_tests
    COMMAND "${PYTHON_EXECUTABLE}" -B -m unittest discover -s tests -t . -v
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
  )
endif()

ament_package()
