#     Copyright 2016, Kay Hayen, mailto:kay.hayen@gmail.com
#
#     Part of "Nuitka", an optimizing Python compiler that is compatible and
#     integrates with CPython, but also works on its own.
#
#     Licensed under the Apache License, Version 2.0 (the "License");
#     you may not use this file except in compliance with the License.
#     You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.
#
""" Code generation for calls.

The different kinds of calls get dedicated code. Most notable, calls with
only positional arguments, are attempted through helpers that might be
able to execute them without creating the argument dictionary at all.

"""

from .ConstantCodes import getConstantAccess
from .ErrorCodes import getErrorExitCode, getReleaseCode, getReleaseCodes
from .Helpers import generateChildExpressionCode
from .LineNumberCodes import emitLineNumberUpdateCode
from .templates.CodeTemplatesCalls import (
    template_call_function_with_args_decl,
    template_call_function_with_args_impl
)
from .templates.CodeTemplatesModules import (
    template_header_guard,
    template_helper_impl_decl
)


def generateCallCode(to_name, expression, emit, context):
    # There is a whole lot of different cases, for each of which, we create
    # optimized code, constant, with and without positional or keyword arguments
    # each, so there is lots of branches here. pylint: disable=R0912

    called_name = generateChildExpressionCode(
        expression = expression.getCalled(),
        emit       = emit,
        context    = context
    )

    call_args = expression.getCallArgs()
    call_kw = expression.getCallKw()

    if call_kw is None or \
       (call_kw.isExpressionConstantRef() and call_kw.getConstant() == {}):
        if call_args is None or call_args.isExpressionConstantRef():
            context.setCurrentSourceCodeReference(
                expression.getCompatibleSourceReference()
            )

            if call_args is not None:
                call_args_value = call_args.getConstant()
            else:
                call_args_value = ()

            assert type(call_args_value) is tuple

            if call_args is not None and call_args.isMutable():
                call_arg_names = []

                for call_arg_element in call_args_value:
                    call_arg_name = context.allocateTempName("call_arg_element")

                    getConstantAccess(
                        to_name  = call_arg_name,
                        constant = call_arg_element,
                        emit     = emit,
                        context  = context,
                    )

                    call_arg_names.append(call_arg_name)

                getCallCodePosArgsQuick(
                    to_name     = to_name,
                    called_name = called_name,
                    arg_names   = call_arg_names,
                    needs_check = expression.mayRaiseException(BaseException),
                    emit        = emit,
                    context     = context
                )
            elif call_args_value:
                getCallCodePosArgs(
                    to_name     = to_name,
                    called_name = called_name,
                    args_name   = context.getConstantCode(
                        constant = call_args_value
                    ),
                    needs_check = expression.mayRaiseException(BaseException),
                    emit        = emit,
                    context     = context
                )
            else:
                getCallCodeNoArgs(
                    to_name     = to_name,
                    called_name = called_name,
                    needs_check = expression.mayRaiseException(BaseException),
                    emit        = emit,
                    context     = context
                )
        elif call_args.isExpressionMakeTuple():
            call_arg_names = []

            for call_arg_element in call_args.getElements():
                call_arg_name = generateChildExpressionCode(
                    child_name = call_args.getChildName() + "_element",
                    expression = call_arg_element,
                    emit       = emit,
                    context    = context,
                )

                call_arg_names.append(call_arg_name)

            context.setCurrentSourceCodeReference(
                expression.getCompatibleSourceReference()
            )

            getCallCodePosArgsQuick(
                to_name     = to_name,
                called_name = called_name,
                arg_names   = call_arg_names,
                needs_check = expression.mayRaiseException(BaseException),
                emit        = emit,
                context     = context
            )
        else:
            args_name = generateChildExpressionCode(
                expression = call_args,
                emit       = emit,
                context    = context
            )

            context.setCurrentSourceCodeReference(
                expression.getCompatibleSourceReference()
            )

            getCallCodePosArgs(
                to_name     = to_name,
                called_name = called_name,
                args_name   = args_name,
                needs_check = expression.mayRaiseException(BaseException),
                emit        = emit,
                context     = context
            )
    else:
        if call_args is None or \
           (call_args.isExpressionConstantRef() and \
            call_args.getConstant() == ()):
            call_kw_name = generateChildExpressionCode(
                expression = call_kw,
                emit       = emit,
                context    = context
            )

            context.setCurrentSourceCodeReference(
                expression.getCompatibleSourceReference()
            )

            getCallCodeKeywordArgs(
                to_name      = to_name,
                called_name  = called_name,
                call_kw_name = call_kw_name,
                emit         = emit,
                context      = context
            )
        else:
            call_args_name = generateChildExpressionCode(
                expression = call_args,
                emit       = emit,
                context    = context
            )

            call_kw_name = generateChildExpressionCode(
                expression = call_kw,
                emit       = emit,
                context    = context
            )

            context.setCurrentSourceCodeReference(
                expression.getCompatibleSourceReference()
            )

            getCallCodePosKeywordArgs(
                to_name        = to_name,
                called_name    = called_name,
                call_args_name = call_args_name,
                call_kw_name   = call_kw_name,
                emit           = emit,
                context        = context
            )


def getCallCodeNoArgs(to_name, called_name, needs_check, emit, context):
    emitLineNumberUpdateCode(emit, context)

    emit(
        "%s = CALL_FUNCTION_NO_ARGS( %s );" % (
            to_name,
            called_name
        )
    )

    getReleaseCode(
        release_name = called_name,
        emit         = emit,
        context      = context
    )

    getErrorExitCode(
        check_name  = to_name,
        emit        = emit,
        needs_check = needs_check,
        context     = context
    )

    context.addCleanupTempName(to_name)



# Outside helper code relies on some quick call to be present.
quick_calls_used = set([1, 2, 3])

def getCallCodePosArgsQuick(to_name, called_name, arg_names, needs_check,
                            emit, context):

    arg_size = len(arg_names)
    quick_calls_used.add(arg_size)

    # For 0 arguments, NOARGS is supposed to be used.
    assert arg_size > 0

    emitLineNumberUpdateCode(emit, context)

    emit(
        "%s = CALL_FUNCTION_WITH_ARGS%d( %s, %s );" % (
            to_name,
            arg_size,
            called_name,
            ", ".join(arg_names)
        )
    )

    getReleaseCodes(
        release_names = [called_name] + arg_names,
        emit          = emit,
        context       = context
    )

    getErrorExitCode(
        check_name  = to_name,
        needs_check = needs_check,
        emit        = emit,
        context     = context
    )

    context.addCleanupTempName(to_name)


def getCallCodePosArgs(to_name, called_name, args_name, needs_check, emit, context):
    emitLineNumberUpdateCode(emit, context)

    emit(
        "%s = CALL_FUNCTION_WITH_POSARGS( %s, %s );" % (
            to_name,
            called_name,
            args_name
        )
    )

    getReleaseCodes(
        release_names = (called_name, args_name),
        emit          = emit,
        context       = context
    )

    getErrorExitCode(
        check_name  = to_name,
        needs_check = needs_check,
        emit        = emit,
        context     = context
    )

    context.addCleanupTempName(to_name)


def getCallCodeKeywordArgs(to_name, called_name, call_kw_name, emit, context):
    emitLineNumberUpdateCode(emit, context)

    emit(
        "%s = CALL_FUNCTION_WITH_KEYARGS( %s, %s );" % (
            to_name,
            called_name,
            call_kw_name
        )
    )

    getReleaseCodes(
        release_names = (called_name, call_kw_name),
        emit          = emit,
        context       = context
    )

    getErrorExitCode(
        check_name = to_name,
        emit       = emit,
        context    = context
    )

    context.addCleanupTempName(to_name)


def getCallCodePosKeywordArgs(to_name, called_name, call_args_name,
                              call_kw_name, emit, context):
    emitLineNumberUpdateCode(emit, context)

    emit(
        "%s = CALL_FUNCTION( %s, %s, %s );" % (
            to_name,
            called_name,
            call_args_name,
            call_kw_name
        )
    )

    getReleaseCodes(
        release_names = (called_name, call_args_name, call_kw_name),
        emit          = emit,
        context       = context
    )

    getErrorExitCode(
        check_name = to_name,
        emit       = emit,
        context    = context
    )

    context.addCleanupTempName(to_name)


def getCallsDecls():
    result = []

    for quick_call_used in sorted(quick_calls_used):
        args_decl = [
            "PyObject *arg%d" % d
            for d in range(quick_call_used)
        ]

        result.append(
            template_call_function_with_args_decl % {
                "args_decl"  : ", ".join(args_decl),
                "args_count" : quick_call_used
            }
        )

    return template_header_guard % {
        "header_guard_name" : "__NUITKA_CALLS_H__",
        "header_body"       : '\n'.join(result)
    }


def getCallsCode():
    result = []

    result.append(
        template_helper_impl_decl % {}
    )

    for quick_call_used in sorted(quick_calls_used):
        args_decl = [
            "PyObject *arg%d" % d
            for d in range(1, quick_call_used + 1)
        ]
        args_list = [
            "arg%d" % d
            for d in range(1, quick_call_used + 1)
        ]

        result.append(
            template_call_function_with_args_impl % {
                "args_decl"  : ", ".join(args_decl),
                "args_list"  : ", ".join(args_list),
                "args_count" : quick_call_used
            }
        )

    return '\n'.join(result)
